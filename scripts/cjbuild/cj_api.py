"""Minimal CJ Dropshipping API 2.0 client (read-only endpoints only).

Only documented product / logistic reads are wrapped here; the skill never places CJ orders.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import BuildError, load_cached_token, load_cj_credentials, save_cached_token

BASE = "https://developers.cjdropshipping.com/api2.0/v1"
MIN_INTERVAL = 0.35  # seconds between calls; CJ throttles bursts
RETRY_CODES = {1600200, 1600201}  # too many requests / busy


class CJClient:
    def __init__(self, token=None, points_reserve=2000):
        self.token = token
        self.points = None
        self.points_reserve = points_reserve
        self.calls = 0
        self._last = 0.0

    # ---------------------------------------------------------------- transport
    def _raw(self, method, path, params=None, body=None, auth=True):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["CJ-Access-Token"] = self.token
        data = json.dumps(body).encode("utf-8") if body is not None else None
        wait = MIN_INTERVAL - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=60) as r:
                    text = r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 3:
                    raise BuildError("CJ_NETWORK", f"{path}: {e}")
                time.sleep(2 * (attempt + 1))
                continue
            finally:
                self._last = time.time()
            self.calls += 1
            try:
                res = json.loads(text)
            except ValueError:
                raise BuildError("CJ_BAD_JSON", f"{path}: non-JSON response: {text[:200]}")
            pts = res.get("pointsInfo") or {}
            if "remaining" in pts:
                self.points = pts
            if res.get("code") in RETRY_CODES and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            return res
        raise BuildError("CJ_RETRY_EXHAUSTED", path)

    def call(self, method, path, params=None, body=None):
        if self.token is None:
            self.authenticate()
        if self.points and self.points.get("remaining", 10 ** 9) < self.points_reserve:
            raise BuildError("CJ_POINTS_LOW", "daily CJ API points nearly exhausted; stopping to keep a reserve",
                             {"points": self.points})
        res = self._raw(method, path, params, body)
        if not res.get("result"):
            raise BuildError("CJ_API_ERROR", f"{path}: {res.get('message')}", {"code": res.get("code"), "params": params})
        return res.get("data")

    # ---------------------------------------------------------------- auth
    def authenticate(self, force=False):
        if not force:
            cached = load_cached_token()
            if cached:
                self.token = cached
                return self.token
        creds = load_cj_credentials()
        res = self._raw("POST", "/authentication/getAccessToken",
                        body={"email": creds["CJ_EMAIL"], "password": creds["CJ_API_KEY"]}, auth=False)
        if not res.get("result"):
            raise BuildError("CJ_AUTH_FAILED", res.get("message", "authentication failed"))
        d = res["data"]
        self.token = d["accessToken"]
        save_cached_token(self.token, d.get("accessTokenExpiryDate"))
        return self.token

    # ---------------------------------------------------------------- reads
    def categories(self):
        return self.call("GET", "/product/getCategory") or []

    def list_products(self, page=1, size=100, category_id=None, keyword=None, country_code=None, product_type=None):
        return self.call("GET", "/product/list", {
            "pageNum": page, "pageSize": size, "categoryId": category_id, "productNameEn": keyword,
            "countryCode": country_code, "productType": product_type}) or {}

    def product(self, pid):
        return self.call("GET", "/product/query", {"pid": pid}) or {}

    def stock(self, vid):
        return self.call("GET", "/product/stock/queryByVid", {"vid": vid}) or []

    def freight(self, vid, end_country, start_country="CN", qty=1):
        return self.call("POST", "/logistic/freightCalculate",
                         body={"startCountryCode": start_country, "endCountryCode": end_country,
                               "products": [{"quantity": qty, "vid": vid}]}) or []
