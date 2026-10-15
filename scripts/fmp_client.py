#!/usr/bin/env python3
"""
Minimal client for the Financial Modeling Prep (FMP) *stable* API.

- Standard library only (no pip install needed); works on Windows, macOS and Linux.
- The API key is read from the FMP_API_KEY environment variable. It never appears
  in cache files or printed output.
- Responses are cached on disk (fundamentals change quarterly, prices daily; the live quote for a minute).
- Endpoints that your plan does not include raise RestrictedEndpoint
  (or return None via try_get) instead of crashing an analysis.

Connection settings (environment variables):
  FMP_API_KEY       required. Official FMP key, or the token a proxy service gave you.
  FMP_BASE_URL      default https://financialmodelingprep.com . Set it to use a
                    third-party proxy, e.g. https://1.2.3.4
  FMP_PATH_PREFIX   path before the endpoint name (default "stable"; auto-detected for proxies)
  FMP_AUTH_STYLE    how the key is sent: header | bearer | x-api-key | query
                    (default "header" = FMP's apikey header; auto-detected for proxies)
  FMP_TLS_VERIFY    "0" turns off HTTPS certificate verification (needed for many
                    bare-IP proxies; less secure). Default "1".
  FMP_MAX_PER_MIN   request rate cap shared by all threads (default 280).
  FMP_MAX_WORKERS   parallel requests analyze.py may run (default 6; 1 = one at a time).
  FMP_TIMEOUT       seconds to wait for each response (default 30).

CLI:
  python fmp_client.py check [SYMBOL]          connection info + which endpoints work
                                               (company, sector/industry and macro data)
  python fmp_client.py check --peek            same, plus field names and first/last rows
                                               of each sector/macro response
  python fmp_client.py get ENDPOINT k=v ...    raw JSON from any stable endpoint
  python fmp_client.py clear-cache             delete the local cache and saved detection
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OFFICIAL_BASE = "https://financialmodelingprep.com"
OFFICIAL_HOSTS = {"financialmodelingprep.com", "www.financialmodelingprep.com"}
DEFAULT_CACHE_DIR = Path(
    os.environ.get("FMP_CACHE_DIR") or (Path.home() / ".cache" / "fmp-fundamentals")
)
AUTH_STYLES = ("header", "bearer", "x-api-key", "query")
PREFIX_CANDIDATES = ("stable", "")

DAY = 86400
TTL_BY_ENDPOINT = {
    "quote": 60,  # the analysis takes its price from here, so a new run shows the current price
    "profile": DAY,
    "historical-price-eod/light": DAY // 2,
    "historical-price-eod/full": DAY // 2,
    "price-target-consensus": DAY,
    "analyst-estimates": 3 * DAY,
    "stock-peers": 7 * DAY,
    "income-statement": 7 * DAY,
    "balance-sheet-statement": 7 * DAY,
    "cash-flow-statement": 7 * DAY,
    "key-metrics": 7 * DAY,
    "ratios": 7 * DAY,
    "financial-growth": 7 * DAY,
    # market-wide data used by macro.py (requests carry from/to dates, so a new day is a new key)
    "treasury-rates": DAY // 4,
    "market-risk-premium": DAY,
    "economic-indicators": DAY // 2,
    "economic-calendar": 3 * 3600,
    "sector-performance-snapshot": DAY // 2,
    "historical-sector-pe": DAY // 2,
    "historical-industry-pe": DAY // 2,
    "historical-sector-performance": DAY // 2,
    "historical-industry-performance": DAY // 2,
}
DEFAULT_TTL = DAY

# Phrases FMP uses when a plan does not cover an endpoint, symbol or parameter.
RESTRICTED_MARKERS = (
    "restricted",
    "subscription",
    "upgrade",
    "premium",
    "not available under your current",
    "exclusive",
)


class FMPError(Exception):
    """Any failure talking to FMP."""


class RestrictedEndpoint(FMPError):
    """The endpoint (or this symbol / parameter) is not included in the current plan."""


class InvalidKey(FMPError):
    """Missing or rejected API key."""


def _error_message(body: str):
    """Return FMP's error text if the body is an error payload, else None."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if isinstance(data, dict):
        for k in ("Error Message", "error", "Error"):
            if k in data and data[k]:
                return str(data[k])
        if "message" in data and len(data) <= 2:
            return str(data["message"])
    return None


def _env_flag(name, default=True):
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() not in ("0", "false", "no", "off")


def _is_timeout(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()


def _is_cert_error(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (ssl.SSLCertVerificationError, ssl.CertificateError)) or \
        "CERTIFICATE_VERIFY_FAILED" in str(reason)


class FMPClient:
    def __init__(self, api_key=None, cache_dir=None, use_cache=True, refresh=False,
                 max_per_min=None, timeout=30):
        self.api_key = (api_key or os.environ.get("FMP_API_KEY", "")).strip()
        if not self.api_key:
            raise InvalidKey(
                "FMP_API_KEY is not set. Set it as an environment variable "
                "(Windows: setx FMP_API_KEY \"your_key\", then open a new terminal)."
            )
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.use_cache = use_cache
        self.refresh = refresh
        per_min = max_per_min or int(os.environ.get("FMP_MAX_PER_MIN", "280"))
        self.rate = max(per_min, 1) / 60.0  # requests per second
        self.burst = min(10.0, float(max(per_min, 1)))
        try:
            self.timeout = float(os.environ.get("FMP_TIMEOUT") or timeout)
        except ValueError:
            self.timeout = timeout
        self._tokens, self._refilled = self.burst, time.time()
        self._lock = threading.Lock()  # guards the rate limiter, stats and the lists below
        self.stats = {"network_calls": 0, "cache_hits": 0}
        self.restricted = []  # endpoints skipped because the plan lacks them
        self.errors = []      # optional endpoints that failed for other reasons

        base = (os.environ.get("FMP_BASE_URL") or OFFICIAL_BASE).strip().rstrip("/")
        if "://" not in base:
            base = "https://" + base
        self.base = base
        self.host = urllib.parse.urlparse(base).hostname or base
        self.is_official = self.host.lower() in OFFICIAL_HOSTS
        self.tls_verify = _env_flag("FMP_TLS_VERIFY", True)
        self._ssl_ctx = None if self.tls_verify else ssl._create_unverified_context()
        if not self.tls_verify:
            print(f"[fmp] WARNING: HTTPS certificate verification is OFF for {self.host} "
                  f"(FMP_TLS_VERIFY=0).", file=sys.stderr)

        env_prefix = os.environ.get("FMP_PATH_PREFIX")
        env_style = (os.environ.get("FMP_AUTH_STYLE") or "").strip().lower() or None
        if env_style and env_style not in AUTH_STYLES:
            raise FMPError(f"FMP_AUTH_STYLE must be one of {', '.join(AUTH_STYLES)}")
        self.prefix = env_prefix.strip("/") if env_prefix is not None else None
        self.auth_style = env_style
        self.connection_source = "environment"
        if self.is_official:
            self.prefix = "stable" if self.prefix is None else self.prefix
            self.auth_style = self.auth_style or "header"
            self.connection_source = "official defaults" if not (env_prefix or env_style) else "environment"
        elif self.prefix is None or self.auth_style is None:
            saved = self._load_saved()
            if saved and not refresh:
                self.prefix = saved["prefix"] if self.prefix is None else self.prefix
                self.auth_style = self.auth_style or saved["style"]
                self.connection_source = "saved detection"
            else:
                self.detect()

    # ------------------------------------------------------------------ connection
    def _url(self, endpoint, params, prefix=None, style=None):
        prefix = self.prefix if prefix is None else prefix
        style = style or self.auth_style
        params = dict(params)
        if style == "query":
            params["apikey"] = self.api_key
        path = "/".join(p for p in (prefix, endpoint) if p)
        query = ("?" + urllib.parse.urlencode(params)) if params else ""
        return f"{self.base}/{path}{query}"

    def _headers(self, style):
        h = {"Accept": "application/json", "User-Agent": "fmp-fundamental-analysis-skill/1.1"}
        if style == "header":
            h["apikey"] = self.api_key
        elif style == "bearer":
            h["Authorization"] = f"Bearer {self.api_key}"
        elif style == "x-api-key":
            h["X-API-Key"] = self.api_key
        return h

    def _saved_path(self):
        return self.cache_dir / "connection.json"

    def _load_saved(self):
        try:
            data = json.loads(self._saved_path().read_text(encoding="utf-8"))
            entry = data.get(self.base)
            if entry and entry.get("style") in AUTH_STYLES and "prefix" in entry:
                return entry
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def _save(self):
        try:
            path = self._saved_path()
            data = {}
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            data[self.base] = {"prefix": self.prefix, "style": self.auth_style}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def detect(self, symbol="AAPL"):
        """Find the path prefix and auth style a proxy accepts, by probing `profile`."""
        print(f"[fmp] Detecting request format for {self.host} (waits up to {self.timeout:g}s "
              f"per try) ...", file=sys.stderr, flush=True)
        prefixes = [self.prefix] if self.prefix is not None else list(PREFIX_CANDIDATES)
        styles = [self.auth_style] if self.auth_style else list(AUTH_STYLES)
        seen = []
        for prefix in prefixes:
            for style in styles:
                url = self._url("profile", {"symbol": symbol}, prefix, style)
                for attempt in range(2):  # one retry if the server is momentarily slow
                    try:
                        status, body = self._http_get(url, style)
                        break
                    except (urllib.error.URLError, OSError) as e:  # OSError covers read timeouts
                        if _is_cert_error(e):
                            raise FMPError(self._cert_hint())
                        if attempt == 0 and _is_timeout(e):
                            continue
                        raise FMPError(self._unreachable_hint(e))
                self._count("network_calls")
                ok = status == 402 or (status == 200 and _error_message(body) is None
                                       and body.strip()[:1] in ("[", "{"))
                seen.append(f"/{prefix or ''} + {style}: HTTP {status}")
                if ok:
                    self.prefix, self.auth_style = prefix, style
                    self.connection_source = "auto-detected"
                    self._save()
                    return
        raise FMPError(
            f"Could not find a working request format for {self.host}. Tried: "
            + "; ".join(seen)
            + ". Check FMP_API_KEY / FMP_BASE_URL, or set FMP_PATH_PREFIX and FMP_AUTH_STYLE "
              "to match the proxy's documentation."
        )

    def _unreachable_hint(self, exc):
        msg = f"cannot reach {self.host}: {getattr(exc, 'reason', exc)}."
        if _is_timeout(exc):
            msg += (f" The server sent no response within {self.timeout:g}s (tried twice). It may be "
                    f"down or overloaded: try again in a few minutes, or set FMP_TIMEOUT=60.")
        return msg

    def _cert_hint(self):
        return (f"HTTPS certificate verification failed for {self.host}. This is common for "
                f"proxies addressed by a bare IP. To run anyway, set FMP_TLS_VERIFY=0 "
                f"(traffic can then be intercepted; see SKILL.md).")

    def describe(self):
        route = "official FMP API" if self.is_official else f"third-party proxy at {self.host}"
        return {
            "route": route, "base": self.base, "prefix": self.prefix, "auth_style": self.auth_style,
            "source": self.connection_source, "tls_verify": self.tls_verify,
        }

    # ------------------------------------------------------------------ low level
    def _http_get(self, url, style=None):
        req = urllib.request.Request(url, headers=self._headers(style or self.auth_style))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            return e.code, body

    def _cache_path(self, endpoint, params):
        key = self.base + "|" + endpoint + "?" + urllib.parse.urlencode(sorted(params.items()))
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        safe_ep = endpoint.replace("/", "_")
        sym = "".join(c for c in str(params.get("symbol", "all")) if c.isalnum() or c in ".-_")
        return self.cache_dir / f"{safe_ep}__{sym}__{digest}.json"

    def _count(self, key):
        with self._lock:
            self.stats[key] += 1

    def _throttle(self):
        """Token bucket shared by all threads: short bursts of up to 10 requests, and
        about FMP_MAX_PER_MIN per minute over time. A caller that finds the bucket empty
        reserves the next token and sleeps until it is due."""
        with self._lock:
            now = time.time()
            self._tokens = min(self.burst, self._tokens + (now - self._refilled) * self.rate)
            self._refilled = now
            self._tokens -= 1
            wait = -self._tokens / self.rate if self._tokens < 0 else 0.0
        if wait > 0:
            time.sleep(wait)

    def _fetch(self, endpoint, params):
        url = self._url(endpoint, params)
        last_err = None
        for attempt in range(4):
            self._throttle()
            try:
                status, body = self._http_get(url)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if _is_cert_error(e):
                    raise FMPError(self._cert_hint())
                last_err = FMPError(f"network error on {endpoint}: {getattr(e, 'reason', e)}"
                                    + (f" (no response within {self.timeout:g}s)" if _is_timeout(e) else ""))
                time.sleep(2 ** attempt)
                continue
            self._count("network_calls")
            if status == 429 or status >= 500:
                last_err = FMPError(f"HTTP {status} on {endpoint} (rate limit or server error)")
                time.sleep(2 ** attempt + 1)
                continue
            msg = _error_message(body)
            low = (msg or "").lower()
            if status == 401 or "invalid api key" in low:
                hint = "" if self.is_official else " (proxy: run `fmp_client.py check` to re-detect the request format)"
                raise InvalidKey(f"key rejected on {endpoint}: {msg or status}{hint}")
            if status in (402, 403) or any(m in low for m in RESTRICTED_MARKERS):
                detail = (msg or body or f"HTTP {status}").strip().replace("\n", " ")[:160]
                raise RestrictedEndpoint(f"{endpoint}: not included in your plan ({detail})")
            if status >= 400:
                raise FMPError(f"HTTP {status} on {endpoint}: {(msg or body)[:200]}")
            if msg:
                raise FMPError(f"{endpoint}: {msg[:200]}")
            if not body.strip():
                return []
            try:
                return json.loads(body)
            except ValueError:
                raise FMPError(f"{endpoint}: response was not JSON: {body[:120]!r}")
        raise last_err or FMPError(f"{endpoint}: failed after retries")

    # ------------------------------------------------------------------ public
    def get(self, endpoint, ttl=None, **params):
        """GET a stable endpoint, e.g. get('income-statement', symbol='AAPL', limit=5)."""
        endpoint = endpoint.strip("/")
        params = {k: v for k, v in params.items() if v is not None}
        ttl = TTL_BY_ENDPOINT.get(endpoint, DEFAULT_TTL) if ttl is None else ttl
        path = self._cache_path(endpoint, params)
        if self.use_cache and not self.refresh and path.exists():
            if time.time() - path.stat().st_mtime < ttl:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._count("cache_hits")
                    return data
                except (OSError, ValueError):
                    pass
        data = self._fetch(endpoint, params)
        if self.use_cache:
            # write-then-rename so a parallel reader never sees a half-written file
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp, path)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return data

    def try_get(self, endpoint, **params):
        """Like get(), but returns None (and records why) for optional data."""
        try:
            return self.get(endpoint, **params)
        except InvalidKey:
            raise
        except RestrictedEndpoint:
            extra = ", ".join(f"{k}={v}" for k, v in params.items()
                              if k not in ("symbol", "page", "from", "to"))
            label = f"{endpoint} ({extra})" if extra else endpoint
            with self._lock:
                if label not in self.restricted:
                    self.restricted.append(label)
        except FMPError as e:
            with self._lock:
                self.errors.append(str(e))
        return None

    def unrestrict(self, endpoint):
        """Drop earlier 'not in your plan' notes for an endpoint that later succeeded."""
        with self._lock:
            self.restricted[:] = [x for x in self.restricted if not x.startswith(endpoint)]

    def add_error(self, msg):
        with self._lock:
            self.errors.append(msg)

    # ------------------------------------------------------------------ helpers
    def profile(self, symbol):
        data = self.get("profile", symbol=symbol)
        if isinstance(data, list):
            return data[0] if data else None
        return data or None

    def statements(self, kind, symbol, period="annual", limit=5, optional=False):
        """kind: 'income-statement' | 'balance-sheet-statement' | 'cash-flow-statement'.
        Returns rows sorted oldest -> newest. Falls back to limit=5 if a longer
        history is restricted by the plan."""
        getter = self.try_get if optional else self.get
        try:
            rows = getter(kind, symbol=symbol, period=period, limit=limit)
        except RestrictedEndpoint:
            if limit > 5:
                rows = getter(kind, symbol=symbol, period=period, limit=5)
            else:
                raise
        if rows is None and optional and limit > 5:
            rows = self.try_get(kind, symbol=symbol, period=period, limit=5)
        if not isinstance(rows, list):
            return [] if rows is None else [rows]
        return sorted(rows, key=lambda r: str(r.get("date", "")))

    def prices(self, symbol, start, end):
        """Daily closes [(date, price)] oldest -> newest."""
        data = self.get("historical-price-eod/light", symbol=symbol, **{"from": start, "to": end})
        if isinstance(data, dict):  # some responses wrap rows in "historical"
            data = data.get("historical", [])
        out = []
        for r in data or []:
            p = r.get("price", r.get("close", r.get("adjClose")))
            if r.get("date") and isinstance(p, (int, float)):
                out.append((str(r["date"])[:10], float(p)))
        return sorted(out)

    def ohlc(self, symbol, start, end):
        """Daily bars [(date, open, high, low, close, volume)] oldest -> newest (the UI's candlestick chart).
        Rows missing any of open/high/low/close are skipped; volume may be None."""
        data = self.get("historical-price-eod/full", symbol=symbol, **{"from": start, "to": end})
        if isinstance(data, dict):
            data = data.get("historical", [])
        out = []
        for r in data or []:
            o, h, lo, c = (r.get(k) for k in ("open", "high", "low", "close"))
            if r.get("date") and all(isinstance(v, (int, float)) for v in (o, h, lo, c)):
                v = r.get("volume")
                out.append((str(r["date"])[:10], float(o), float(h), float(lo), float(c),
                            float(v) if isinstance(v, (int, float)) else None))
        return sorted(out)


# ---------------------------------------------------------------------- CLI
PROBES = [
    ("profile", {}),
    ("quote", {}),
    ("income-statement", {"period": "annual", "limit": 5}),
    ("income-statement", {"period": "annual", "limit": 10}),
    ("income-statement", {"period": "quarter", "limit": 4}),
    ("balance-sheet-statement", {"period": "annual", "limit": 5}),
    ("cash-flow-statement", {"period": "annual", "limit": 5}),
    ("key-metrics", {"period": "annual", "limit": 5}),
    ("ratios", {"period": "annual", "limit": 5}),
    ("financial-growth", {"period": "annual", "limit": 5}),
    ("historical-price-eod/light", {}),
    ("historical-price-eod/full", {}),
    ("stock-peers", {}),
    ("analyst-estimates", {"period": "annual", "page": 0, "limit": 10}),
    ("price-target-consensus", {}),
]


# Market-wide data (no symbol): sector/industry and macro endpoints the skill may use.
# {today}, {month_ago}, {week_ago}, {in_2w} and {last_bday} are filled in at run time.
MARKET_PROBES = [
    ("sector-performance-snapshot", {"date": "{last_bday}"}),
    ("industry-performance-snapshot", {"date": "{last_bday}"}),
    ("historical-sector-performance", {"sector": "Technology"}),
    ("historical-sector-performance", {"sector": "Technology", "from": "{year_ago}", "to": "{today}"}),
    ("sector-pe-snapshot", {"date": "{last_bday}"}),
    ("industry-pe-snapshot", {"date": "{last_bday}"}),
    ("historical-sector-pe", {"sector": "Technology"}),
    ("historical-sector-pe", {"sector": "Technology", "from": "{five_years_ago}", "to": "{today}"}),
    ("historical-industry-pe", {"industry": "Consumer Electronics", "from": "{five_years_ago}", "to": "{today}"}),
    ("historical-industry-performance", {"industry": "Consumer Electronics", "from": "{year_ago}", "to": "{today}"}),
    ("historical-price-eod/light", {"symbol": "SPY", "from": "{month_ago}", "to": "{today}"}),
    ("treasury-rates", {"from": "{month_ago}", "to": "{today}"}),
    ("treasury-rates", {"from": "{year_ago}", "to": "{today}"}),
    ("market-risk-premium", {}),
    ("economic-indicators", {"name": "federalFunds"}),
    ("economic-indicators", {"name": "federalFunds", "from": "{two_years_ago}", "to": "{today}"}),
    ("economic-indicators", {"name": "CPI", "from": "{two_years_ago}", "to": "{today}"}),
    ("economic-indicators", {"name": "inflationRate"}),
    ("economic-indicators", {"name": "unemploymentRate", "from": "{two_years_ago}", "to": "{today}"}),
    ("economic-indicators", {"name": "realGDP", "from": "{two_years_ago}", "to": "{today}"}),
    ("economic-calendar", {"from": "{week_ago}", "to": "{in_2w}"}),
    ("earnings-calendar", {"from": "{week_ago}", "to": "{in_2w}"}),
]


def _peek(data):
    """Field names plus the first and last rows, for working out a response's shape."""
    rows = data if isinstance(data, list) else [data]
    show = lambda r: json.dumps(r, ensure_ascii=False, default=str)[:400]
    lines = [f"      fields: {', '.join(rows[0].keys()) if isinstance(rows[0], dict) else type(rows[0]).__name__}",
             f"      first : {show(rows[0])}"]
    if len(rows) > 1:
        lines.append(f"      last  : {show(rows[-1])}")
    # rows the macro features will look for: the US risk premium and key US calendar events
    dicts = [r for r in rows if isinstance(r, dict)]
    us = [r for r in dicts if "united states" in str(r.get("country", "")).lower()
          or str(r.get("country", "")).upper() in ("US", "USA")]
    if us and "event" in dicts[0]:
        keys = ("cpi", "ppi", "pce", "fed", "fomc", "interest rate", "nonfarm", "gdp")
        hits = [r for r in us if any(k in str(r.get("event", "")).lower() for k in keys)]
        lines += [f"      US    : {show(r)}" for r in hits[:12]]
    elif us:
        lines.append(f"      US    : {show(us[0])}")
    return "\n".join(lines)


def _probe(client, ep, params, peek=False):
    try:
        data = client.get(ep, **params)
        n = len(data) if isinstance(data, list) else (1 if data else 0)
        if n and peek:
            return "OK", f"{n} rows\n{_peek(data)}"
        return ("OK", f"{n} rows") if n else ("EMPTY", "no rows returned")
    except RestrictedEndpoint as e:
        return "RESTRICTED", str(e).split("(", 1)[-1].rstrip(")")[:60]
    except InvalidKey:
        raise
    except FMPError as e:
        return "ERROR", str(e)[:60]


def _cmd_check(symbol, peek=False):
    client = FMPClient(refresh=True)
    c = client.describe()
    print("Connection")
    print(f"  route       : {c['route']}")
    print(f"  base URL    : {c['base']}")
    print(f"  path prefix : /{c['prefix'] or ''}")
    print(f"  auth style  : {c['auth_style']}  ({c['source']})")
    print(f"  TLS verify  : {'on' if c['tls_verify'] else 'OFF'}")
    print(f"\nProbing company endpoints with {symbol} ...\n")
    print(f"{'endpoint':<30} {'params':<28} {'result':<11} detail")
    print("-" * 92)
    now = time.time()
    day = lambda offset: time.strftime("%Y-%m-%d", time.localtime(now + offset * DAY))
    last_bday = next(day(-i) for i in range(1, 8)
                     if time.localtime(now - i * DAY).tm_wday < 5)
    dates = {"today": day(0), "month_ago": day(-30), "week_ago": day(-7), "in_2w": day(14),
             "last_bday": last_bday, "year_ago": day(-365), "two_years_ago": day(-730),
             "five_years_ago": day(-1826)}
    try:
        for ep, params in PROBES:
            label = " ".join(f"{k}={v}" for k, v in params.items() if k != "page")
            if ep.startswith("historical-price"):
                params = dict(params, **{"from": dates["month_ago"], "to": dates["today"]})
                label = "last 30 days"
            result, detail = _probe(client, ep, dict(params, symbol=symbol))
            print(f"{ep:<30} {label:<28} {result:<11} {detail}")
        print("\nProbing sector/industry and macro endpoints ...\n")
        print(f"{'endpoint':<30} {'params':<38} {'result':<11} detail")
        print("-" * 102)
        for ep, params in MARKET_PROBES:
            params = {k: v.format(**dates) for k, v in params.items()}
            label = " ".join(f"{k}={v}" for k, v in params.items() if k not in ("from", "to"))
            if "from" in params:
                label = (label + f" {params['from']}..{params['to']}").strip()
            result, detail = _probe(client, ep, params, peek)
            print(f"{ep:<30} {label:<38} {result:<11} {detail}")
    except InvalidKey as e:
        print(f"\nKey problem: {e}")
        return 2
    print(f"\nNetwork calls used: {client.stats['network_calls']}")
    return 0


def _cmd_get(endpoint, kvs):
    params = {}
    for kv in kvs:
        if "=" not in kv:
            print(f"Ignoring argument without '=': {kv}", file=sys.stderr)
            continue
        k, v = kv.split("=", 1)
        params[k] = v
    client = FMPClient()
    print(json.dumps(client.get(endpoint, **params), indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "check":
            rest = [a for a in argv[1:] if a != "--peek"]
            return _cmd_check((rest[0] if rest else "AAPL").upper(), peek="--peek" in argv)
        if cmd == "get" and len(argv) >= 2:
            return _cmd_get(argv[1], argv[2:])
        if cmd == "clear-cache":
            shutil.rmtree(DEFAULT_CACHE_DIR, ignore_errors=True)
            print(f"Cleared {DEFAULT_CACHE_DIR}")
            return 0
    except FMPError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
