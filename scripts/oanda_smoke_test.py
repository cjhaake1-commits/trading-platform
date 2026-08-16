from src.oanda_practice import OandaPracticeClient


def main():
    client = OandaPracticeClient()
    summary = client.account_summary()["account"]
    instrument = "EUR_USD"
    pricing = client.price(instrument)["prices"][0]

    print("OANDA PRACTICE CONNECTION: OK")
    print(f"Account: ...{summary['id'][-4:]}")
    print(f"Currency: {summary['currency']}")
    print(f"Balance: {summary['balance']}")
    print(f"NAV: {summary['NAV']}")
    print(f"Open trades: {summary['openTradeCount']}")
    print(f"{instrument} bid: {pricing['bids'][0]['price']}")
    print(f"{instrument} ask: {pricing['asks'][0]['price']}")
    print("No order was submitted.")


if __name__ == "__main__":
    main()
