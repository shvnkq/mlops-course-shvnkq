"""One connection per attempt. Coordinates clients by a wall anchor, measures on monotonic clock."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import http.client
import json
import os
import socket
import time


def attempt(host, row, timeout=16):
    record = {**row, "source_ip":os.getenv("POD_IP"), "client":socket.gethostname(),
              "sent_ns":None,"first_ns":None,"ended_ns":None,"status":None,"chunks":0,
              "pod":None,"version":None,"backend_mode":None,"warmed":None,"queue_seconds":None,
              "cache_hit":None,"inter_chunk_seconds":[],"outcome":"not_sent"}
    conn = http.client.HTTPConnection(host, 8080, timeout=timeout)
    record["sent_ns"], record["sent_wall_ns"] = time.monotonic_ns(), time.time_ns()
    answer = []
    try:
        conn.request("POST", "/generate", json.dumps(row["payload"]),
                     {"Content-Type":"application/json","Connection":"close","X-Request-ID":row["id"]})
        response = conn.getresponse()
        record.update(status=response.status,pod=response.getheader("X-Pod"),
                      version=response.getheader("X-Model-Version"),
                      backend_mode=response.getheader("X-Backend-Mode"),
                      warmed=response.getheader("X-Warmed"))
        if response.status != 200:
            response.read()
            record["outcome"] = "rejected" if response.status == 429 else "http_error"
        else:
            previous = None
            record["outcome"] = "aborted"
            done = False
            for line in response:
                arrived = time.monotonic_ns()
                fragment = json.loads(line)
                if fragment["type"] == "done":
                    record["server_total_seconds"] = fragment["total_seconds"]
                    done = fragment["chunks"] == record["chunks"] == row["payload"]["chunks"]
                if fragment["type"] == "chunk":
                    if previous is None:
                        record.update(first_ns=arrived, queue_seconds=fragment["queue_seconds"],
                                      cache_hit=fragment["cache_hit"], runtime_sha256=fragment["runtime_sha256"])
                        if row.get("notify_first"):
                            print(json.dumps({"event":"first","id":row["id"],"pod":record["pod"],
                                              "ts":time.time()}), flush=True)
                    else:
                        record["inter_chunk_seconds"].append((arrived - previous)/1e9)
                    previous = arrived
                    record["chunks"] += 1
                    answer.append(fragment["text"])
            if done:
                record["outcome"] = "ok"
    except TimeoutError as exc:
        record.update(outcome="timeout", error=str(exc))
    except (OSError, http.client.HTTPException, ValueError) as exc:
        record.update(outcome="aborted", error=type(exc).__name__ + ": " + str(exc))
    finally:
        conn.close()
        record["ended_ns"], record["ended_wall_ns"] = time.monotonic_ns(), time.time_ns()
        record["answer"] = "".join(answer)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("epoch", type=int)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=96) as pool:
        anchor_ns = time.monotonic_ns() + (args.epoch - time.time_ns())
        futures = []
        for row in sorted(json.load(__import__("sys").stdin), key=lambda r:r["offset_s"]):
            target = anchor_ns + round(row["offset_s"] * 1e9)
            time.sleep(max(0, (target - time.monotonic_ns()) / 1e9))
            item = {**row, "scheduled_ns":target,
                    "scheduled_wall_ns":args.epoch + round(row["offset_s"]*1e9)}
            futures.append(pool.submit(attempt, args.host, item))
        for future in futures:
            print(json.dumps(future.result(),ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
