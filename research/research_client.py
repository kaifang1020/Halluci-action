import os
import xmlrpc.client


class OdooClient:
    def __init__(
        self,
        url: str | None = None,
        db: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.url = url or os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = db or os.getenv("ODOO_DB", "odoo_research")
        self.username = username or os.getenv("ODOO_USER", "admin")
        self.password = password or os.getenv("ODOO_PASSWORD", "admin")

        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(
            self.db,
            self.username,
            self.password,
            {},
        )
        if not self.uid:
            raise RuntimeError("Odoo authentication failed")

        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def call(self, model: str, method: str, args=None, kwargs=None):
        return self.models.execute_kw(
            self.db,
            self.uid,
            self.password,
            model,
            method,
            args or [],
            kwargs or {},
        )


if __name__ == "__main__":
    client = OdooClient()
    partners = client.call(
        "res.partner",
        "search_read",
        [[["customer_rank", ">", 0]]],
        {"fields": ["name", "email", "phone"], "limit": 5},
    )
    print(partners)
