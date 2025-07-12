# 2double - Cross-Chain Bridge Event Listener Simulation

This repository contains a Python-based simulation of a critical component for a cross-chain bridge: the **Event Listener**. This script is designed to monitor a source blockchain for specific events (e.g., tokens being locked in a bridge contract) and then simulate the corresponding action on a destination chain (e.g., minting wrapped tokens).

This project serves as an architectural blueprint, demonstrating a robust, modular, and scalable design for building real-world blockchain infrastructure components.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain to another. A common mechanism is **Lock-and-Mint**: a user locks their assets in a smart contract on the source chain, and an equivalent amount of "wrapped" assets are minted for them on the destination chain.

The Event Listener (or "Validator Node") is the backbone of this system. It has one primary job: to reliably watch the source chain for `TokensLocked` events. Once an event is detected, the listener must:

1.  **Validate** the event to ensure it's legitimate.
2.  **Process** the event data (who locked tokens, how much, and for whom on the destination chain).
3.  **Trigger** the corresponding minting transaction on the destination chain.

This script simulates this entire workflow in a structured and fault-tolerant manner.

## Code Architecture

The system is designed with a clear separation of concerns, with each class handling a specific responsibility. This makes the code easier to test, maintain, and extend.

```
+-----------------------+
|  BridgeOrchestrator   | (Main loop, state management)
+-----------+-----------+
            |
            | Initializes & Coordinates
            v
+-----------------------+      +-----------------------+      +-----------------------+
|      EventScout       |----->|  BlockchainConnector  |      |      BridgeOracle     |
| (Scans for events)    |      | (Web3 connection)     |      | (External data, e.g., prices)|
+-----------------------+      +-----------------------+      +-----------------------+
            |
            | Dispatches Events
            v
+-----------------------+
|  TransactionProcessor | (Business logic, validation, simulation)
+-----------------------+

```

### Core Components

-   **`BlockchainConnector`**: A reusable wrapper around the `web3.py` library. It manages the connection to an RPC node and provides methods for fetching blocks and interacting with contracts.

-   **`EventScout`**: Its sole purpose is to scan block ranges for a specific smart contract event (`TokensLocked`). It uses the `BlockchainConnector` to communicate with the chain.

-   **`BridgeOracle`**: Simulates an external data provider. It uses the `requests` library to fetch data from a real-world API (like CoinGecko) to enrich the validation process, for example, by checking the USD value of a transfer.

-   **`TransactionProcessor`**: This is where the core business logic resides. When the `EventScout` finds an event, it's passed here. The processor validates the event's data, uses the `BridgeOracle` for additional checks (e.g., for high-value transactions), and finally simulates the action that would occur on the destination chain.

-   **`BridgeOrchestrator`**: The main class that ties everything together. It initializes all other components, manages the main application loop, keeps track of the last processed block (state management), and handles graceful shutdowns.

## How it Works

The script follows a continuous, stateful polling mechanism.

1.  **Initialization**: The `BridgeOrchestrator` is created. It sets up the `BlockchainConnector`, `EventScout`, `TransactionProcessor`, and `BridgeOracle` using configuration from a `.env` file.

2.  **State Sync**: On startup, the orchestrator determines the latest block number on the source chain. It sets its starting point to scan from the previous block to ensure no events are missed.

3.  **Polling Loop**: The orchestrator enters an infinite loop where it:
    a.  Fetches the current latest block number.
    b.  Compares it with the `last_processed_block` to see if there are new blocks to scan.
    c.  If new blocks exist, it instructs the `EventScout` to scan a small range (e.g., 100 blocks) to find `TokensLocked` events.
    d.  If any events are found, they are passed one-by-one to the `TransactionProcessor`.

4.  **Event Processing**: For each event, the `TransactionProcessor`:
    a.  Extracts and validates event arguments (amount, recipient, destination chain ID).
    b.  Performs advanced checks, such as using the `BridgeOracle` to get the USD value of the transfer and flag it if it exceeds a security threshold.
    c.  Calls a simulation method (`_simulate_destination_mint`) that logs the details of the transaction that would have been broadcast on the destination chain.

5.  **State Update**: After scanning a block range, the orchestrator updates `last_processed_block`. In a production system, this value would be persisted to a database to allow the listener to resume from where it left off after a restart.

6.  **Repeat**: The loop continues, ensuring the listener stays in sync with the source chain with minimal delay.

## Usage Example

### 1. Setup Environment

First, clone the repository and install the required dependencies.

```bash
git clone <your-repo-url>/2double.git
cd 2double
pip install -r requirements.txt
```

### 2. Configure

Create a `.env` file in the root of the project directory. This file will hold your configuration, preventing you from hardcoding sensitive information like RPC URLs.

```
# .env file

# RPC URL for the source blockchain you want to listen to (e.g., Goerli testnet).
# You can get one from services like Infura, Alchemy, or Ankr.
SOURCE_CHAIN_RPC_URL="https://rpc.ankr.com/eth_goerli"

# (Optional) The address of the bridge contract to monitor.
# The default is a placeholder address.
BRIDGE_CONTRACT_ADDRESS="0x26911325776632497673523528A55516394235a9"
```

### 3. Run the Script

Execute the script from your terminal.

```bash
python script.py
```

### 4. Expected Output

The script will start logging its activities to the console. You will see messages indicating a successful connection, block scanning progress, and details of any events it finds and processes.

```
2023-10-27 14:30:00 - INFO - [blockchain_connector.connect] - Successfully connected to blockchain node. Chain ID: 5
2023-10-27 14:30:00 - INFO - [__main__.run] - Bridge Orchestrator initialized successfully.
2023-10-27 14:30:01 - INFO - [__main__.run] - Starting the cross-chain bridge listener...
2023-10-27 14:30:02 - INFO - [__main__.run] - Starting scan from block: 9981234
2023-10-27 14:30:17 - INFO - [__main__.run] - Caught up to block 9981235. Waiting for next block...
...
2023-10-27 14:30:45 - INFO - [event_scout.scan_blocks] - Scanning blocks from 9981236 to 9981240...
2023-10-27 14:30:46 - INFO - [__main__.run] - Found 1 new 'TokensLocked' event(s) between blocks 9981236 and 9981240.
2023-10-27 14:30:46 - INFO - [transaction_processor.process_lock_event] - Processing new 'TokensLocked' event from transaction: 0xabc123...
2023-10-27 14:30:46 - INFO - [transaction_processor.process_lock_event] - Event Details: Recipient=0x..., Amount=500000000000000000, DestChain=80001, Token=0x...
2023-10-27 14:30:47 - INFO - [transaction_processor._simulate_destination_mint] - --- SIMULATING DESTINATION CHAIN ACTION ---
2023-10-27 14:30:47 - INFO - [transaction_processor._simulate_destination_mint] - Recipient: 0xRecipientAddress...
2023-10-27 14:30:47 - INFO - [transaction_processor._simulate_destination_mint] - Amount (wei): 500000000000000000
2023-10-27 14:30:47 - INFO - [transaction_processor._simulate_destination_mint] - Action: A transaction would be created to mint wrapped tokens on chain ID 80001.
2023-10-27 14:30:47 - INFO - [transaction_processor._simulate_destination_mint] - --- SIMULATION COMPLETE ---
```
