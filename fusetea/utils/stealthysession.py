import os
import requests


class StealthySession(requests.Session):
    def __init__(self, headers=None):
        super().__init__()
        self.verify = False
        self.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.3485.81",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.5",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }
        )

        if headers:
            for header in headers:
                header, value = header.split(":", 1)
                value = value.lstrip()
                if header == "Cookie":
                    # for eZ access later on
                    self.cookies.update(
                        dict(item.strip().split("=", 1) for item in value.split(";"))
                    )
                else:
                    self.headers.update({header: value})

        self.proxies.update(
            {
                "http": os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY"),
                "https": os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY"),
            }
        )
