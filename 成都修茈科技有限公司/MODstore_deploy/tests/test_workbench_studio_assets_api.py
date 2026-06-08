from __future__ import annotations


def test_studio_assets_upload_list_download_delete(client, auth_headers, tmp_path, monkeypatch):
    data_root = tmp_path / "studio_data"
    monkeypatch.setenv("MODSTORE_DATA_DIR", str(data_root))

    files = {"file": ("note.txt", b"hello studio", "text/plain")}
    r = client.post("/api/workbench/studio-assets", files=files, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("id")
    assert body.get("filename") == "note.txt"
    aid = int(body["id"])

    r2 = client.get("/api/workbench/studio-assets", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    lst = r2.json()
    assert lst.get("total") == 1
    assert len(lst.get("items") or []) == 1
    assert lst["items"][0]["id"] == aid

    r3 = client.get(f"/api/workbench/studio-assets/{aid}/file", headers=auth_headers)
    assert r3.status_code == 200, r3.text
    assert b"hello studio" in r3.content

    r4 = client.patch(
        f"/api/workbench/studio-assets/{aid}",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"metadata": {"note": "n1", "linked_employee_ids": ["emp_a"]}},
    )
    assert r4.status_code == 200, r4.text
    assert r4.json().get("metadata", {}).get("note") == "n1"

    r5 = client.delete(f"/api/workbench/studio-assets/{aid}", headers=auth_headers)
    assert r5.status_code == 200, r5.text

    r6 = client.get("/api/workbench/studio-assets", headers=auth_headers)
    assert r6.json().get("total") == 0
