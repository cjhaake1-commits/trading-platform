# Broker Architecture for the Initial Autonomous Pilot

## Design decision

The platform must remain broker-agnostic. Strategy, signal fusion, portfolio accounting, market intelligence, and deterministic risk controls live above the broker layer. Each broker implements the same restricted execution interface so capital can migrate later without rewriting the trading logic.

The current intended live pilot