from backend.services.newsletter.mailer import prepare_for_email
from backend.services.newsletter_service import _SimpleTTLCache
import time

def test_ttl_cache_eviction_and_expiry():
    cache = _SimpleTTLCache(maxsize=2, ttl_seconds=0.1)
    
    # Insert 2 items
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    
    # Exceed maxsize -> 'a' should be evicted (LRU)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    
    # Test TTL expiration
    time.sleep(0.15)
    assert cache.get("b") is None
    assert cache.get("c") is None

def test_prepare_for_email_css_var_substitution():
    raw_html = """
    <html>
      <head>
        <style>
          :root {
            --brand-gold: #c5a059;
            --brand-navy: #0d1b2a;
          }
        </style>
      </head>
      <body>
        <div style="color: var(--brand-gold); background-color: var(--brand-navy);">
          Hello Faraglioni
        </div>
      </body>
    </html>
    """
    processed = prepare_for_email(raw_html)
    assert "var(--brand-gold)" not in processed
    assert "var(--brand-navy)" not in processed
    assert "#c5a059" in processed
    assert "#0d1b2a" in processed
