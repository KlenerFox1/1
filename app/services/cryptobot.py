from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class CryptoBotError(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoInvoice:
    invoice_id: str
    status: str
    pay_url: str | None
    amount: float


@dataclass(frozen=True)
class CryptoTransfer:
    transfer_id: str
    status: str


class CryptoBotAPI:
    """
    Minimal async client for Crypto Pay API (CryptoBot).
    Base URL: https://pay.crypt.bot/api
    """

    def __init__(self, api_key: str, *, timeout_sec: float = 20.0) -> None:
        if not api_key:
            raise RuntimeError("CRYPTOBOT_API_KEY is empty")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url="https://pay.crypt.bot/api",
            timeout=timeout_sec,
            headers={"Crypto-Pay-API-Token": api_key},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._client.post(method, json=payload or {})
        data = resp.json()
        if resp.status_code != 200:
            raise CryptoBotError(f"HTTP {resp.status_code}: {data}")
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise CryptoBotError(f"API error: {data}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise CryptoBotError(f"Unexpected result: {data}")
        return result

    async def create_invoice(self, *, amount: float, asset: str = "USDT", description: str = "Deposit") -> CryptoInvoice:
        result = await self._call(
            "/createInvoice",
            {
                "amount": str(amount),
                "asset": asset,
                "description": description,
            },
        )
        return CryptoInvoice(
            invoice_id=str(result.get("invoice_id")),
            status=str(result.get("status", "unknown")),
            pay_url=str(result.get("pay_url")) if result.get("pay_url") else None,
            amount=float(result.get("amount") or amount),
        )

    async def get_invoices(self, *, invoice_ids: list[str]) -> list[CryptoInvoice]:
        if not invoice_ids:
            return []
        result = await self._call("/getInvoices", {"invoice_ids": invoice_ids})
        items = result.get("items") or []
        out: list[CryptoInvoice] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                out.append(
                    CryptoInvoice(
                        invoice_id=str(it.get("invoice_id")),
                        status=str(it.get("status", "unknown")),
                        pay_url=str(it.get("pay_url")) if it.get("pay_url") else None,
                        amount=float(it.get("amount") or 0.0),
                    )
                )
        return out

    async def transfer(self, *, user_id: int, amount: float, asset: str = "USDT", comment: str = "Withdrawal") -> CryptoTransfer:
        result = await self._call(
            "/transfer",
            {
                "user_id": user_id,
                "asset": asset,
                "amount": str(amount),
                "comment": comment,
            },
        )
        return CryptoTransfer(
            transfer_id=str(result.get("transfer_id") or result.get("id") or ""),
            status=str(result.get("status", "unknown")),
        )

    async def get_balance(self) -> list[dict[str, Any]]:
        result = await self._call("/getBalance", {})
        items = result.get("items") or []
        return items if isinstance(items, list) else []

    async def get_asset_balance(self, asset: str = "USDT") -> float:
        items = await self.get_balance()
        for it in items:
            if not isinstance(it, dict):
                continue
            if str(it.get("currency_code") or it.get("asset") or "") == asset:
                try:
                    return float(it.get("available") or it.get("available_balance") or it.get("balance") or 0.0)
                except Exception:
                    return 0.0
        return 0.0

