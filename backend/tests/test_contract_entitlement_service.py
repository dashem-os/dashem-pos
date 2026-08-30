from app.services.contract_entitlement_service import build_entitlement_snapshot


def test_contract_snapshot_copies_offer_and_records_provenance():
    proposal = {
        "activity_keys": ["RETAIL", "BEAUTY_RESELLER"],
        "capabilities": [
            {
                "key": "catalog",
                "sources": ["ACTIVITY", "PLAN"],
                "activity_keys": ["BEAUTY_RESELLER", "RETAIL"],
            },
            {
                "key": "receivables",
                "sources": ["ADDON", "PLAN"],
                "activity_keys": ["BEAUTY_RESELLER", "RETAIL"],
            },
        ],
    }

    snapshot = build_entitlement_snapshot(
        proposal=proposal,
        users=20,
        devices=5,
        units=2,
        storage_mb=4096,
    )

    assert snapshot["schema_version"] == 2
    assert snapshot["activity_keys"] == ["RETAIL", "BEAUTY_RESELLER"]
    assert snapshot["capability_keys"] == ["catalog", "receivables"]
    assert snapshot["capability_entitlements"][1]["sources"] == ["ADDON", "OWNER_DECISION", "PLAN"]
    assert snapshot["limit_entitlements"]["users"] == {
        "limit": 20,
        "sources": ["PLAN", "OWNER_DECISION"],
    }
    assert snapshot["storage_entitlement"] == {
        "limit_mb": 4096,
        "sources": ["PLAN", "OWNER_DECISION"],
        "measurement_status": "NOT_MEASURED",
    }


def test_contract_snapshot_is_detached_from_mutable_offer_collections():
    proposal = {
        "activity_keys": ["RETAIL"],
        "capabilities": [
            {
                "key": "catalog",
                "sources": ["ACTIVITY", "PLAN"],
                "activity_keys": ["RETAIL"],
            }
        ],
    }
    snapshot = build_entitlement_snapshot(
        proposal=proposal,
        users=5,
        devices=1,
        units=1,
        storage_mb=1024,
    )

    proposal["activity_keys"].append("FOOD_SERVICE")
    proposal["capabilities"][0]["sources"].append("ADDON")

    assert snapshot["activity_keys"] == ["RETAIL"]
    assert snapshot["capability_entitlements"][0]["sources"] == ["ACTIVITY", "OWNER_DECISION", "PLAN"]
