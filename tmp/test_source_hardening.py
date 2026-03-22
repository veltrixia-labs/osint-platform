import json

# Mock items to test the filtering logic implemented in report_job.py
class MockItem:
    def __init__(self, title, summary, source_url, source_name="News"):
        self.title = title
        self.summary = summary
        self.source_url = source_url
        self.source_name = source_name

items = [
    MockItem("Real News Artikel", "This is a real article.", "https://realsource.com/art1"),
    MockItem("Mock Item Heading", "This is a dummy summary.", "https://example.com/bad"),
    MockItem("Test Report 2026", "Ingested for testing.", "http://localhost:5173/"),
    MockItem("Valid Defense Intel", "Critical update on defense.", "https://defensenews.io/strat1"),
    MockItem("Invalid Link", "No protocol here.", "broken-link.com"),
    MockItem("Empty Link", "Nothing here.", ""),
    MockItem("Short Link", "Too short.", "http://a.bc")
]

# Validation Logic copied from report_job.py
BANNED_DOMAINS = ["example.com", "localhost", "127.0.0.1", "test.com", "dummy.org", "maritime-intel-example.org"]

def test_filtering():
    results = []
    for it in items:
        url = (it.source_url or "").lower()
        
        is_valid_url = (
            url.startswith("http") and 
            not any(d in url for d in BANNED_DOMAINS) and
            len(url) > 12
        )
        
        is_mock_data = any(kw in (it.title or "").lower() or kw in (it.summary or "").lower() for kw in ["mock item", "test report", "dummy article"])
        
        final_url = url if (is_valid_url and not is_mock_data) else "#"
        
        results.append({
            "title": it.title,
            "original_url": it.source_url,
            "final_url": final_url,
            "is_valid": is_valid_url,
            "is_mock": is_mock_data
        })
    
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    test_filtering()
