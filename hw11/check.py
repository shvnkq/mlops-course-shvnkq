"""Assertions over raw live Kubernetes experiments, with optional live HTTP smoke."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import unittest
import time

from experiments import RESULTS, get, ready_pods, traffic, dialog


def read(name):
    return [json.loads(line) for line in (RESULTS/name).read_text().splitlines()]


class LiveEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = read("requests.jsonl")
        cls.timeline = read("timeline.jsonl")
        cls.events = read("events.jsonl")

    def rows(self, phase):
        rows = [r for r in self.records if r["phase"]==phase]
        self.assertTrue(rows,phase)
        return rows

    def test_01_warmup_defect_and_fix(self):
        before = self.rows("a-early")
        after = self.rows("a-fixed")
        self.assertTrue(any(r["outcome"]=="ok" and r["warmed"]=="false" for r in before))
        self.assertTrue(all(r["outcome"]=="ok" and r["warmed"]=="true" for r in after))
        snapshots = [t for t in self.timeline if t["phase"]=="a-fixed"]
        self.assertTrue(any(not p["ready"] and
            all(not e.get("ready") for e in t["endpoints"] if e["pod"]==p["name"])
            for t in snapshots for p in t["pods"]))

    def test_02_rollback_loaded_artifact(self):
        sha = hashlib.sha256((Path(__file__).parent/"chart/models/A.json").read_bytes()).hexdigest()
        bad = self.rows("a-bad")
        self.assertEqual({r["version"] for r in bad},{"A"})
        candidates = [(t,p) for t in self.timeline if t["phase"]=="a-bad"
                      for p in t["pods"] if p["version"]=="B"]
        self.assertTrue(candidates)
        self.assertTrue(all(not p["ready"] and
                            all(not ep.get("ready") for ep in t["endpoints"] if ep["pod"]==p["name"])
                            for t,p in candidates))
        self.assertTrue(all(r["outcome"]=="ok" and r["warmed"]=="true"
                           and r["runtime_sha256"]==sha for r in self.rows("a-rollback")))
        self.assertTrue(any("artifact SHA-256 mismatch" in p.read_text()
                            for p in (RESULTS/"server").glob("a-bad-*.log")))

    def test_03_replacement_restores_version_and_context(self):
        before = self.rows("a-dialog-before")[0]
        after = next(r for r in self.rows("a-dialog-after") if r["payload"]["session_id"]=="GEONAMES-ALPHA-714")
        for row in (before,after):
            self.assertEqual((row["version"], row["outcome"]),("A","ok"))
            self.assertIn("GEONAMES-ALPHA-714",row["answer"])
        self.assertEqual(before["runtime_sha256"],after["runtime_sha256"])
        self.assertNotEqual(before["pod"],after["pod"])
        replacements = [e for e in self.events if e["event"]=="replacement_ready"]
        self.assertTrue(any(e["old"]==before["pod"] and e["new"]==after["pod"] for e in replacements))

    def test_04_classification_rejections_and_aborted_streams(self):
        row = self.rows("a-kill-stream")[0]
        self.assertEqual((row["status"],row["outcome"]),(200,"aborted"))
        self.assertGreaterEqual(row["chunks"],1)
        self.assertLess(row["chunks"],row["payload"]["chunks"])
        refused = [r for r in self.records if r["outcome"]=="rejected"]
        self.assertTrue(refused)
        self.assertTrue(all(r["status"]==429 and r["chunks"]==0 for r in refused))
        self.assertEqual(len(self.records),len({r["id"] for r in self.records}))

    def test_05_dialogue_isolation_one_pod(self):
        rows = self.rows("a-dialog-after")
        self.assertEqual(len(rows),2)
        self.assertEqual(len({r["pod"] for r in rows}),1)
        for row,other in (rows,rows[::-1]):
            self.assertIn(row["payload"]["session_id"],row["answer"])
            self.assertNotIn(other["payload"]["session_id"],row["answer"])

    def test_06_graceful_rollout(self):
        rows = self.rows("a-rollout") + [r for r in self.records if r["phase"].startswith("a-rollout-drain")]
        crossing = self.rows("a-rollout-cross")[0]
        begin = next(e["ts"] for e in self.events if e["phase"]=="a-rollout" and e["event"]=="upgrade")
        self.assertLess(crossing["sent_wall_ns"]/1e9,begin)
        self.assertGreater(crossing["ended_wall_ns"]/1e9,begin)
        self.assertEqual(crossing["outcome"],"ok")
        self.assertEqual({r["version"] for r in rows},{"A","B"})
        self.assertTrue(all(r["outcome"]=="ok" or
                            (r["status"]==429 and r["outcome"]=="rejected" and r["chunks"]==0)
                            for r in rows))
        logs = [json.loads(line) for p in (RESULTS/"server").glob("a-retiring-*.log")
                for line in p.read_text().splitlines() if line.startswith("{")]
        self.assertTrue(any(item["event"]=="drain_started" and item["running"]>0 and
                            any(r["pod"]==item["pod"] and
                                r["sent_wall_ns"]/1e9<=item["ts"]<r["ended_wall_ns"]/1e9
                                for r in rows)
                            for item in logs))

    def test_07_open_loop_and_repetitions(self):
        for distribution in ("even","hot"):
            for rep in range(1,4):
                regular = sorted(self.rows(f"b-{distribution}-plain-{rep}"),key=lambda r:r["offset_s"])
                affinity = sorted(self.rows(f"b-{distribution}-affinity-{rep}"),key=lambda r:r["offset_s"])
                self.assertEqual(len(regular),600)
                contents = lambda rows: [(r["offset_s"],r["source_ip"],r["payload"]) for r in rows]
                self.assertEqual(contents(regular),contents(affinity))
                for rows in (regular,affinity):
                    self.assertEqual(len({r["source_ip"] for r in rows}),4)
                    self.assertEqual(rows[-1]["offset_s"],119.8)
                    self.assertEqual(Counter(r["client_index"] for r in rows)[0],
                                     480 if distribution=="hot" else 150)

    def test_08_histogram_counts_match_client_successes(self):
        key = "hw11_ttfc_seconds_bucket"
        for path in RESULTS.glob("b-*-prom.json"):
            data = json.loads(path.read_text())
            def count(side):
                return sum(float(item["value"][1]) for item in data[side][key] if item["metric"]["le"]=="+Inf")
            phase = path.name.removesuffix("-prom.json")
            self.assertEqual(count("after")-count("before"),
                             sum(r["outcome"]=="ok" for r in self.rows(phase)),phase)

    def test_09_autoscaler_and_alert_transitions(self):
        current = [r["hpa"].get("currentReplicas") for r in self.timeline if r["phase"]=="c-hpa"]
        middle = current.index(3)
        self.assertIn(2,current[:middle])
        self.assertIn(2,current[middle+1:])
        samples = [e for e in read("alert-states.jsonl") if e["phase"]=="c-hpa"]
        binding = {r["source_ip"]:r["pod"] for r in self.rows("c-affinity-seed")}
        self.assertEqual(len(binding),4)
        self.assertTrue(all(r["pod"]==binding[r["source_ip"]] for r in self.rows("c-hpa-hot")))
        for name in ("FirstChunkSlow","RequestFailures"):
            states = [next((a["state"] for a in t["alerts"] if a["labels"]["alertname"]==name),"inactive") for t in samples]
            pending = states.index("pending")
            firing = states.index("firing",pending)
            self.assertIn("inactive",states[firing+1:])


class Smoke(unittest.TestCase):
    def test_http_at_cluster_service(self):
        rows = traffic("inference",[dialog(f"smoke-{time.time_ns()}",i,marker=f"live-marker-{i}") for i in range(4)])
        for row in rows:
            self.assertEqual((row["outcome"],row["version"],row["warmed"],row["backend_mode"]),
                             ("ok","A","true","simulated"))
            self.assertIn(row["payload"]["session_id"],row["answer"])
        self.assertEqual(len(ready_pods()),2)
        for service,affinity in (("inference","None"),("inference-affinity","ClientIP")):
            self.assertEqual(get("svc",service)["spec"]["sessionAffinity"],affinity)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",action="store_true")
    args = parser.parse_args()
    suite = unittest.TestLoader().loadTestsFromTestCase(LiveEvidence)
    if args.live:
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(Smoke))
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
