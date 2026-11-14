#!/usr/bin/env python3
"""check-merged -- the product-document validators on the merged view, in a feature cycle
(increment 7c; Amendment 3 FC: "feature additions get the full product-document validators,
not a lighter check"; the gap increment 6 left).

    check_merged.py --phase <label>

Run by the gate's worker in feature scope. It exports HEAD into a scratch tree (git archive:
the commit judged, no .git), copies the product's adopted config (.sdlc/product.yaml and
.sdlc/config/), writes the feature's additions into the product documents exactly as APPROVE 11
would merge them (gate/feature.py merge_plan), and runs, on that tree, every product-scope
validator the registry lists for this phase among the product-document validators
(check-handoff, check-profile, check-threat-model, check-lld, check-provisioning). Their own
FAIL/UNKNOWN lines are reported under their names.

Exit 0 every merged validator passes; 1 a failure (or a merge that would collide); 2 unknown.
Phases whose documents are not merged (7 and later) have no entry in the registry. An onboarded product's
merged view is judged by check-baseline's completeness rules (ruling 3 on increment 7c).
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

GATE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(GATE))
sys.path.insert(0, os.path.join(GATE, "v1"))

from gate import feature, state, validate  # noqa: E402
import hlib  # noqa: E402
import toolrun  # noqa: E402

PRODUCT_DOC_MODULES = ("check_handoff", "check_profile", "check_threat_model", "check_lld", "check_provisioning")


def export(root, dest):
    p = subprocess.run([state.GIT, "-C", root, "archive", "--format=tar", "HEAD"], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("git archive HEAD failed: %s" % p.stderr.decode(errors="replace")[:200])
    with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
        members = [m for m in tf.getmembers() if not (m.name.startswith("/") or ".." in m.name.split("/") or
                                                      m.issym() or m.islnk())]
        tf.extractall(dest, members=members)  # noqa: S202 (names checked: no absolute, no .., no links)


def main(argv):
    if len(argv) != 2 or argv[0] != "--phase":
        print("UNKNOWN usage: check_merged.py --phase <label>")
        return 2
    label = argv[1]
    root = os.environ.get("MOADIX_PRODUCT_ROOT") or os.getcwd()
    try:
        st, problems = state.current_state(root)
        if problems:
            print("UNKNOWN gate state failed its integrity check: %s" % "; ".join(problems))
            return 2
        fid = st.get("feature")
        if not fid:
            print("OK no feature cycle is active; the product's own validators judge the product documents")
            return 0
        onboarded = st.get("mode") == "onboarding"
        if onboarded:
            # Ruling 3 on increment 7c: an onboarded product's documents follow the baseline shape, so its merged
            # view is judged by check-baseline's completeness rules (sections, goals, stories, gaps register, no
            # secrets, never production), not by the greenfield validators; citations are not required of the
            # feature's additions.
            comps = [c for c in validate.validators_for("B", "product") if str(c.get("module")) == "check_baseline"]
        else:
            comps = [c for c in validate.validators_for(label, "product") if str(c.get("module")) in PRODUCT_DOC_MODULES]
        if not comps:
            print("OK phase %s has no product-document validator to run on the merged view" % label)
            return 0
        tmp = toolrun.mkdtemp("moadix-merged-")
        try:
            tree = os.path.join(tmp, "tree")
            os.makedirs(tree)
            export(root, tree)
            os.makedirs(os.path.join(tree, ".sdlc"), exist_ok=True)
            shutil.copy(os.path.join(root, ".sdlc", "product.yaml"), os.path.join(tree, ".sdlc", "product.yaml"))
            if os.path.isdir(os.path.join(root, ".sdlc", "config")):
                shutil.copytree(os.path.join(root, ".sdlc", "config"), os.path.join(tree, ".sdlc", "config"),
                                dirs_exist_ok=True)
            try:
                plan = feature.merge_plan(tree, fid)
            except feature.FeatureError as e:
                print("FAIL the feature's additions cannot be merged into the product documents: %s" % e)
                return 1
            for target, data in plan["contents"].items():
                p = os.path.join(tree, target)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(data)
            doc_path = os.path.join(tmp, "phase-doc.json")
            prod = dict(st, phases=st.get("product_phases") or st["phases"], feature=None)
            with open(doc_path, "w") as f:
                json.dump(hlib.v1_phase_doc(prod), f)
            env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": os.environ.get("HOME", "/var/empty"),
                   "LANG": "en_US.UTF-8", "TMPDIR": tmp, "MOADIX_PRODUCT_ROOT": tree, "MOADIX_PHASE_DOC": doc_path,
                   "MOADIX_GATE_RUN": "yes", "MOADIX_FEATURE": ""}
            if onboarded:
                env["MOADIX_BASELINE_COMPLETENESS_ONLY"] = "1"
            for k in ("MOADIX_GUARD_ROOT", "MOADIX_GUARD_REPO", "MOADIX_GUARD_SHIM"):
                if k in os.environ:
                    env[k] = os.environ[k]
            print("note merged view: %s" % ", ".join(f["target"] for f in plan["files"]))
            worst = 0
            for c in comps:
                rc, out = validate.run_one(tree, c, env)
                res = validate.result_of(rc)
                lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
                if res == "pass":
                    print("OK %s passes on the merged product documents" % c["id"])
                    continue
                tag = "FAIL" if res == "fail" else "UNKNOWN"
                bad = [ln for ln in lines if ln.startswith(("FAIL", "ERR", "UNKNOWN", "MISSING")) or "FAIL" in ln[:12]]
                for ln in (bad or lines[-3:])[:10]:
                    print("%s %s (merged with feature %s): %s" % (tag, c["id"], fid, ln[:300]))
                worst = max(worst, 1 if res == "fail" else 2) if worst != 1 else 1
            return worst
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:  # unknown, never a pass
        print("UNKNOWN the merged view could not be checked: %s: %s" % (type(e).__name__, e))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
