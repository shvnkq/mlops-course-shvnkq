"""Собрать собственный chat-датасет из локальной копии GeoNames."""

import hashlib
import importlib.metadata
import json
import time
from collections import defaultdict
from pathlib import Path

import geonamescache

from src.config import load_params

QUESTION_KINDS = ("country", "population", "coordinates", "timezone")


def stable_index(key: str, size: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def question_answer(kind: str, city: dict, country_name: str, variant: int) -> tuple[str, str]:
    name = city["name"]
    if kind == "country":
        questions = (
            f"В какой стране находится город {name}? Укажи современное название страны.",
            f"Назови страну, на территории которой расположен город {name}.",
            f"К какой стране относится город {name} согласно GeoNames?",
        )
        answer = f"Город {name} находится в стране {country_name}."
    elif kind == "population":
        questions = (
            f"Какова численность населения города {name} в использованном снимке GeoNames?",
            f"Сколько жителей указано для города {name} в исходных данных GeoNames?",
            f"Назови зафиксированное GeoNames население города {name}.",
        )
        answer = f"Для города {name} указано население {int(city['population']):,} человек.".replace(",", " ")
    elif kind == "coordinates":
        questions = (
            f"Укажи географические координаты города {name} по данным GeoNames.",
            f"На какой широте и долготе расположен город {name}?",
            f"Какие координаты приведены в GeoNames для города {name}?",
        )
        answer = (
            f"В десятичной записи координаты города {name}: широта "
            f"{float(city['latitude']):.4f}°, долгота {float(city['longitude']):.4f}°. "
            "В исходных данных координаты приведены в системе WGS 84."
        )
    else:
        questions = (
            f"Какой часовой пояс указан для города {name} в GeoNames?",
            f"Назови часовой пояс, к которому относится город {name}.",
            f"В каком часовом поясе расположен город {name} согласно исходным данным?",
        )
        answer = f"Для города {name} указан часовой пояс {city['timezone']}."
    return questions[variant % len(questions)], answer


def main() -> None:
    params = load_params()
    cfg = params["collect"]
    version = cfg["version"]
    if version not in cfg["versions"]:
        raise SystemExit(f"неизвестная collect.version: {version!r}")
    limits = cfg["versions"][version]
    prompts = cfg["system_prompts"]
    if len(prompts) < 3:
        raise SystemExit("collect.system_prompts должен содержать минимум 3 варианта")

    started = time.perf_counter()
    cache = geonamescache.GeonamesCache()
    countries = cache.get_countries()
    cities_by_country: dict[str, list[dict]] = defaultdict(list)
    for city in cache.get_cities().values():
        code = city.get("countrycode")
        if code in countries and int(city.get("population") or 0) > 0 and city.get("timezone"):
            cities_by_country[code].append(city)

    needed = int(limits["cities_per_country"])
    eligible = [code for code, cities in cities_by_country.items() if len(cities) >= needed]
    eligible.sort(key=lambda code: hashlib.sha256(f"{cfg['seed']}:{code}".encode()).hexdigest())
    selected_codes = eligible[: int(limits["countries"])]
    if len(selected_codes) < int(limits["countries"]):
        raise SystemExit("в источнике недостаточно стран с требуемым числом городов")

    out = Path(params["paths"]["raw"])
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    prompts_used: set[str] = set()
    kind_counts = {kind: 0 for kind in QUESTION_KINDS}
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for code in selected_codes:
            country_name = countries[code]["name"]
            cities = sorted(
                cities_by_country[code],
                key=lambda city: (-int(city["population"]), str(city["geonameid"])),
            )[:needed]
            for city in cities:
                for kind in QUESTION_KINDS:
                    example_id = f"geonames-{version}-{city['geonameid']}-{kind}"
                    prompt = prompts[stable_index(example_id, len(prompts))]
                    question, answer = question_answer(
                        kind, city, country_name, stable_index(example_id + ":q", 3)
                    )
                    record = {
                        "id": example_id,
                        "topic": f"География: {country_name}",
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": question},
                            {"role": "assistant", "content": answer},
                        ],
                    }
                    fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    prompts_used.add(prompt)
                    kind_counts[kind] += 1
                    rows += 1

    metrics = {
        "version": version,
        "source": "GeoNames via geonamescache",
        "geonamescache_version": importlib.metadata.version("geonamescache"),
        "countries": len(selected_codes),
        "cities": len(selected_codes) * needed,
        "rows_written": rows,
        "system_prompt_variants": len(prompts_used),
        "question_kinds": kind_counts,
        "seconds": round(time.perf_counter() - started, 2),
    }
    mpath = Path(params["paths"]["metrics_collect"])
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"collect: {version}, {metrics['countries']} стран, {metrics['cities']} городов, "
        f"{rows} строк, {len(prompts_used)} системных промптов, {metrics['seconds']} с"
    )


if __name__ == "__main__":
    main()
