# Источник данных

Датасет построен на данных [GeoNames](https://www.geonames.org/), полученных
из локального снимка в Python-пакете
[`geonamescache==3.0.2`](https://pypi.org/project/geonamescache/3.0.2/).

- Данные GeoNames: Creative Commons Attribution 4.0 International (CC BY 4.0).
- Код пакета geonamescache: MIT.
- Атрибуция: «GeoNames geographical database — geonames.org».
- Дата сборки учебного набора: 20 сентября 2026 года.

Мы не распространяем исходный снимок через Git. Версия пакета закреплена в
`uv.lock`, а производные JSONL находятся под управлением DVC.
