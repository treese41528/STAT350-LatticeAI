#!/usr/bin/env python3
"""Probe GenAI Studio knowledge-base ACCESS — the piece BYOK "own" mode hinges on.

BYOK "own" mode only helps a student if THEIR account can read the course
collection. Purdue's RCAC GenAI Studio is a *customized* Open WebUI: knowledge
sharing is expressed by an `access_grants` list + a `write_access` bool (NOT
vanilla Open WebUI's `access_control`). Empirically (July 2026):

  - A freshly created KB has `access_grants: []` == shared with NO ONE.
  - The REST API has NO working endpoint to change sharing: `/knowledge/{id}/
    update` accepts an `access_grants` field but silently drops it; every other
    candidate path falls through to the SPA. Sharing is a WEB-UI-only action
    (genai.rcac.purdue.edu → the KB's Access/Share panel).

So this script's real job: run it with a **student / TA (non-owner) key** to
settle the one thing that decides everything —

    can a non-owner key actually RETRIEVE from the course collection?

If yes → BYOK `retrieval: own` works (share it once in the UI, or the gateway
doesn't ACL-check retrieval at all). If no → keep `retrieval: shared`.

Run (key via env — never hardcode/commit it):
    export GENAI_STUDIO_API_KEY=sk-...        # a STUDENT/TA key for the real test
    export GENAI_STUDIO_RPM=20
    ~/venvs/stat350-tutor/bin/python scripts/kb_access_probe.py

--create-test creates a throwaway KB, shows its default sharing, and confirms
the API can't set it public (then deletes it).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings  # noqa: E402

OK, WARN, BAD = "[ok]", "[!]", "[x]"
BASE = Path(__file__).resolve().parents[1]


def make_studio(base_url: str, key: str):
    from genai_studio import GenAIStudio
    return GenAIStudio(api_key=key, base_url=base_url,
                       timeout=30, connect_timeout=15, validate_model=False)


def describe_sharing(rec: dict) -> str:
    """Human reading of the RCAC access_grants / write_access model."""
    grants = rec.get("access_grants")
    if grants is None:
        return "unknown (no access_grants field returned)"
    if not grants:
        return "PRIVATE — access_grants: [] (shared with no one)"
    return f"SHARED — access_grants: {grants!r}"


def whoami(studio) -> dict:
    for path in ("/api/v1/auths/", "/api/v1/users/user/settings"):
        try:
            data = studio._http_get(path).json()
            if isinstance(data, dict) and (data.get("email") or data.get("id")):
                return data
        except Exception:
            continue
    return {}


def list_kbs(studio) -> list[dict]:
    data = studio._http_get("/api/v1/knowledge/").json()
    return data["items"] if isinstance(data, dict) else data


def retrieval_ok(studio, kb_id: str, query="central limit theorem") -> tuple[bool, int]:
    try:
        payload = studio._http_post(
            "/api/v1/retrieval/query/collection",
            json={"collection_names": [kb_id], "k": 3, "hybrid": False,
                  "query": query}).json()
        docs = payload.get("documents") or []
        flat = docs[0] if docs and isinstance(docs[0], list) else docs
        return bool(flat), len(flat or [])
    except Exception as exc:
        print(f"       {WARN} retrieval raised: {type(exc).__name__}: {exc}")
        return False, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create-test", action="store_true",
                    help="create a throwaway KB, show default sharing + that the "
                         "API can't set it public, then delete it")
    args = ap.parse_args()

    settings = load_settings(BASE / "config.yaml")
    key = os.environ.get("GENAI_STUDIO_API_KEY")
    if not key:
        print(f"{BAD} GENAI_STUDIO_API_KEY not set."); return 1
    if not os.environ.get("GENAI_STUDIO_RPM"):
        print(f"{WARN} GENAI_STUDIO_RPM unset — set it to 20 to pace the gateway.")
    studio = make_studio(settings.gateway.base_url, key)

    print("=" * 70)
    print("1. WHOSE KEY IS THIS?")
    me = whoami(studio)
    my_id = me.get("id")
    if me:
        print(f"   {OK} {me.get('email','?')}  role={me.get('role','?')}  id={str(my_id)[:12]}")
    else:
        print(f"   {WARN} couldn't resolve the account; continuing.")

    print("\n2. STAT 350 COLLECTIONS — SHARING + CAN THIS KEY READ THEM?")
    kbs = [k for k in list_kbs(studio) if "STAT 350" in k.get("name", "")]
    if not kbs:
        print(f"   {WARN} this key sees NO STAT 350 knowledge bases.")
    saw_nonowner = False        # did we test ANY collection this key doesn't own?
    saw_nonowner_read = False    # ...and could a non-owner key actually read it?
    for k in kbs:
        owner = k.get("user_id")
        mine = my_id and owner == my_id
        ok, n = retrieval_ok(studio, k["id"])
        print(f"   • {k['name']!r}")
        print(f"       sharing : {describe_sharing(k)}")
        print(f"       owner   : {'THIS key (owner)' if mine else str(owner)[:12]+' (someone else)'}")
        print(f"       read    : {OK+' '+str(n)+' chunks' if ok else BAD+' BLOCKED'}")
        if not mine:
            saw_nonowner = True
            if ok:
                saw_nonowner_read = True
                print(f"       {OK} NON-owner key CAN read it → BYOK 'own' mode works.")
            else:
                print(f"       {BAD} NON-owner key blocked → keep retrieval: shared.")

    print("\n3. VERDICT")
    if not saw_nonowner:
        # every STAT 350 KB is owned by this key → we only proved the OWNER can
        # read, which says nothing about students. This is the inconclusive case.
        print(f"   {WARN} This is the OWNER key for every STAT 350 collection, so the")
        print("        'read=ok' rows above only prove the owner can read — NOT what a")
        print("        student sees. THE DECISIVE TEST: re-run with a STUDENT or TA key.")
    elif saw_nonowner_read:
        print(f"   {OK} A non-owner key read the course materials. Set byok.retrieval: own")
        print("        (share the KB once in the UI if it isn't already).")
    else:
        print(f"   {BAD} A non-owner key could NOT read the course materials.")
        print("        Either share the KB in the web UI, or keep byok.retrieval: shared")
        print("        (retrieval stays on the class key; only generation uses theirs).")

    if args.create_test:
        print("\n4. CREATE-TEST (throwaway) — what can the API do about sharing?")
        kb = studio.create_knowledge_base("BYOK Access Test (safe to delete)", "temp probe")
        rec = studio._http_get(f"/api/v1/knowledge/{kb.id}").json()
        print(f"   {OK} created; DEFAULT sharing = {describe_sharing(rec)}")
        # attempt to set public via the only write endpoint
        studio._http_post(f"/api/v1/knowledge/{kb.id}/update",
                          json={"name": rec.get("name"), "description": "temp",
                                "data": {}, "access_grants": [{"subject_type": "public",
                                                               "permission": "read"}]})
        after = studio._http_get(f"/api/v1/knowledge/{kb.id}").json()
        took = bool(after.get("access_grants"))
        print(f"   {OK if took else BAD} after API update: {describe_sharing(after)}"
              f"  → API {'CAN' if took else 'CANNOT'} set sharing "
              f"({'unexpected' if took else 'confirmed UI-only'}).")
        studio.delete_knowledge_base(kb.id)
        print(f"   {OK} deleted the throwaway KB.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
