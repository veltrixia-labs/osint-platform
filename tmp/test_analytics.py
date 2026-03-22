import httpx

r = httpx.post("http://localhost:8000/api/analytics/event", json={
    "event_type": "preview_view",
    "report_id": "d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2d2",
    "metadata_json": {"visitor_id": "abc", "url": "http://localhost:5173"}
})
print("STATUS:", r.status_code)
print("RESPONSE:", r.text)
