"""The retired point-grid endpoint is an explicit compatibility tombstone."""


def test_regional_scan_is_gone_and_names_the_raster_replacement(client):
    response = client.get("/regional-scan")
    assert response.status_code == 410
    body = response.json()
    assert body["replacement"] == "/raster-scan"
    assert "501-point regional scan" in body["detail"]
    assert "pixel resolution" in body["disclaimer"]


def test_root_lists_the_active_raster_endpoint_instead(client):
    endpoints = client.get("/").json()["endpoints"]
    assert "/raster-scan" in endpoints
    assert "/regional-scan" not in endpoints
