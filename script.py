import os
import json
import time
import logging
from typing import Dict, Any, Optional, List

import requests
from web3 import Web3
from web3.contract import Contract
from web3.logs import DISCARD
from web3.exceptions import BlockNotFound
from dotenv import load_dotenv

# --- Basic Configuration ---
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(module)s.%(funcName)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Constants ---
# In a real application, these would be part of a more extensive configuration system.
SOURCE_CHAIN_RPC_URL = os.getenv('SOURCE_CHAIN_RPC_URL', 'https://rpc.ankr.com/eth_goerli')
BRIDGE_CONTRACT_ADDRESS = os.getenv('BRIDGE_CONTRACT_ADDRESS', '0x26911325776632497673523528A55516394235a9') # Example address
DESTINATION_CHAIN_ID = 80001 # Mumbai Testnet as an example
ORACLE_API_ENDPOINT = 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd'

# A simplified ABI for the bridge contract's 'TokensLocked' event.
# This defines the structure of the event we are listening for.
BRIDGE_CONTRACT_ABI = json.loads('''
[
    {
        "anonymous": false,
        "inputs": [
            {
                "indexed": true,
                "internalType": "address",
                "name": "token",
                "type": "address"
            },
            {
                "indexed": true,
                "internalType": "address",
                "name": "sender",
                "type": "address"
            },
            {
                "indexed": false,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256"
            },
            {
                "indexed": false,
                "internalType": "uint256",
                "name": "destinationChainId",
                "type": "uint256"
            },
            {
                "indexed": false,
                "internalType": "address",
                "name": "recipient",
                "type": "address"
            }
        ],
        "name": "TokensLocked",
        "type": "event"
    }
]
''')

# --- Architectural Components ---

class BlockchainConnector:
    """Manages the connection to a single blockchain via Web3.py."""

    def __init__(self, rpc_url: str):
        """
        Initializes the connector with a given RPC URL.

        Args:
            rpc_url (str): The HTTP RPC endpoint for the blockchain node.
        """
        self.rpc_url = rpc_url
        self.web3: Optional[Web3] = None
        self._connect()

    def _connect(self) -> None:
        """Establishes the connection to the blockchain node."""
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.web3.is_connected():
                raise ConnectionError(f"Failed to connect to blockchain node at {self.rpc_url}")
            logging.info(f"Successfully connected to blockchain node. Chain ID: {self.web3.eth.chain_id}")
        except Exception as e:
            logging.error(f"Error connecting to blockchain node: {e}")
            self.web3 = None

    def get_contract(self, address: str, abi: List[Dict[str, Any]]) -> Optional[Contract]:
        """
        Returns a Web3.py contract instance.

        Args:
            address (str): The contract address.
            abi (List[Dict[str, Any]]): The contract's ABI.

        Returns:
            Optional[Contract]: A contract object or None if not connected.
        """
        if not self.web3 or not self.web3.is_connected():
            logging.warning("Cannot get contract, not connected to blockchain.")
            return None
        
        checksum_address = self.web3.to_checksum_address(address)
        return self.web3.eth.contract(address=checksum_address, abi=abi)

    def get_latest_block_number(self) -> Optional[int]:
        """
        Fetches the latest block number from the connected chain.

        Returns:
            Optional[int]: The latest block number or None on failure.
        """
        if not self.web3 or not self.web3.is_connected():
            logging.warning("Cannot get block number, not connected.")
            return None
        try:
            return self.web3.eth.block_number
        except Exception as e:
            logging.error(f"Failed to fetch latest block number: {e}")
            return None

class BridgeOracle:
    """
    Simulates an oracle that provides external data, such as token prices or security validations.
    Uses the 'requests' library to fetch data from an external API.
    """

    def __init__(self, api_endpoint: str):
        """
        Initializes the oracle with an API endpoint.

        Args:
            api_endpoint (str): The URL of the external data source.
        """
        self.api_endpoint = api_endpoint

    def get_eth_price_in_usd(self) -> Optional[float]:
        """
        Fetches the current price of Ethereum in USD from CoinGecko API.

        Returns:
            Optional[float]: The price of ETH in USD, or None if the request fails.
        """
        try:
            response = requests.get(self.api_endpoint, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
            data = response.json()
            price = data.get('ethereum', {}).get('usd')
            if price:
                logging.info(f"Oracle fetched ETH price: ${price}")
                return float(price)
            else:
                logging.warning("Oracle response did not contain expected price data.")
                return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Oracle API request failed: {e}")
            return None

class TransactionProcessor:
    """
    Processes validated events from the EventScout.
    This component is responsible for business logic, validation, 
    and simulating the execution on the destination chain.
    """

    def __init__(self, oracle: BridgeOracle):
        """
        Initializes the processor with a data oracle.

        Args:
            oracle (BridgeOracle): An oracle for fetching external data for validation.
        """
        self.oracle = oracle
        self.processed_transactions = set()

    def process_lock_event(self, event: Dict[str, Any]) -> None:
        """
        Handles a 'TokensLocked' event.

        Args:
            event (Dict[str, Any]): The parsed event data from a transaction log.
        """
        tx_hash = event['transactionHash'].hex()
        if tx_hash in self.processed_transactions:
            logging.warning(f"Skipping already processed transaction: {tx_hash}")
            return

        logging.info(f"Processing new 'TokensLocked' event from transaction: {tx_hash}")

        # --- 1. Data Extraction and Validation ---
        try:
            event_args = event['args']
            recipient = event_args['recipient']
            amount_wei = event_args['amount']
            destination_chain = event_args['destinationChainId']
            token = event_args['token']

            logging.info(f"Event Details: Recipient={recipient}, Amount={amount_wei}, DestChain={destination_chain}, Token={token}")

            # Basic business logic validation
            if destination_chain != DESTINATION_CHAIN_ID:
                logging.warning(f"Skipping event for unsupported destination chain {destination_chain}")
                return
            
            if amount_wei <= 0:
                logging.error(f"Invalid amount in event: {amount_wei}. Skipping.")
                return

        except KeyError as e:
            logging.error(f"Event data is missing expected key: {e}. Event: {event}")
            return
        
        # --- 2. External Data Validation (using Oracle) ---
        # Example: For high-value transfers, check against a price oracle.
        amount_ether = Web3.from_wei(amount_wei, 'ether')
        if amount_ether > 1: # Let's say any transfer > 1 ETH requires an oracle check
            eth_price = self.oracle.get_eth_price_in_usd()
            if eth_price is not None:
                value_usd = float(amount_ether) * eth_price
                logging.info(f"High-value transfer detected. Amount: {amount_ether:.4f} ETH, Value: ${value_usd:,.2f}")
                if value_usd > 10000: # Additional security threshold
                    logging.warning(f"Transfer value ${value_usd:,.2f} exceeds security threshold. Flagging for manual review.")
                    # In a real system, this might trigger a different workflow.
            else:
                logging.error("Could not verify transfer value with oracle. Halting processing for safety.")
                return

        # --- 3. Simulate Execution on Destination Chain ---
        self._simulate_destination_mint(recipient, amount_wei, token, tx_hash)
        self.processed_transactions.add(tx_hash)

    def _simulate_destination_mint(self, recipient: str, amount: int, token: str, source_tx_hash: str) -> None:
        """
        Simulates the minting of tokens on the destination chain.
        In a real bridge, this would involve creating and signing a transaction
        on the destination chain using a wallet controlled by the validator network.
        """
        logging.info("--- SIMULATING DESTINATION CHAIN ACTION ---")
        logging.info(f"Recipient: {recipient}")
        logging.info(f"Amount (wei): {amount}")
        logging.info(f"Token (source address): {token}")
        logging.info(f"Source Tx Hash: {source_tx_hash}")
        logging.info("Action: A transaction would be created to mint wrapped tokens on chain ID {DESTINATION_CHAIN_ID}.")
        logging.info("--- SIMULATION COMPLETE ---")

class EventScout:
    """
    Scans the source blockchain for relevant events.
    """

    def __init__(self, connector: BlockchainConnector, contract: Contract):
        """
        Initializes the scout.

        Args:
            connector (BlockchainConnector): The connector to the source blockchain.
            contract (Contract): The Web3.py contract object to monitor.
        """
        self.connector = connector
        self.contract = contract

    def scan_blocks(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        """
        Scans a range of blocks for 'TokensLocked' events.

        Args:
            from_block (int): The starting block number.
            to_block (int): The ending block number.

        Returns:
            List[Dict[str, Any]]: A list of found event logs.
        """
        if from_block > to_block:
            return []

        logging.info(f"Scanning blocks from {from_block} to {to_block}...")
        try:
            event_filter = self.contract.events.TokensLocked.create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            events = event_filter.get_all_entries()
            return events
        except BlockNotFound:
            logging.warning(f"Block range not found: {from_block}-{to_block}. The node might not have this history.")
        except Exception as e:
            logging.error(f"An error occurred while scanning blocks: {e}")
        return []

class BridgeOrchestrator:
    """
    The main component that orchestrates the entire listening and processing workflow.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes all components of the bridge listener.

        Args:
            config (Dict[str, Any]): A dictionary containing all necessary configuration.
        """
        self.config = config
        self.is_running = False
        self.last_processed_block = None

        # Initialize components
        self.connector = BlockchainConnector(config['rpc_url'])
        self.oracle = BridgeOracle(config['oracle_endpoint'])
        self.processor = TransactionProcessor(self.oracle)
        
        contract = self.connector.get_contract(config['contract_address'], config['contract_abi'])
        if not contract:
            raise RuntimeError("Failed to initialize bridge contract. Check connection and address.")
        self.scout = EventScout(self.connector, contract)
        
        logging.info("Bridge Orchestrator initialized successfully.")

    def run(self) -> None:
        """
        Starts the main event loop of the listener.
        """
        self.is_running = True
        logging.info("Starting the cross-chain bridge listener...")

        # Determine the starting block
        # In a real system, this would be loaded from a persistent store (DB, file).
        latest_block = self.connector.get_latest_block_number()
        if latest_block is None:
            logging.error("Could not fetch latest block. Shutting down.")
            return
        self.last_processed_block = latest_block - 1 # Start from the block before the current one

        logging.info(f"Starting scan from block: {self.last_processed_block}")

        while self.is_running:
            try:
                current_block = self.connector.get_latest_block_number()
                if current_block is None:
                    logging.warning("Failed to get current block, will retry...")
                    time.sleep(10)
                    continue

                if self.last_processed_block >= current_block:
                    # We are caught up, wait for the next block
                    logging.info(f"Caught up to block {current_block}. Waiting for next block...")
                    time.sleep(15) # Wait time depends on the chain's block time
                    continue

                # Define the range of blocks to scan in this iteration.
                # Process in chunks to avoid overwhelming the RPC node.
                to_block = min(self.last_processed_block + 100, current_block)

                events = self.scout.scan_blocks(self.last_processed_block + 1, to_block)
                if events:
                    logging.info(f"Found {len(events)} new 'TokensLocked' event(s) between blocks {self.last_processed_block + 1} and {to_block}.")
                    for event in events:
                        self.processor.process_lock_event(event)
                
                # Update the last processed block
                # IMPORTANT: This must be done atomically in a real system.
                self.last_processed_block = to_block

            except KeyboardInterrupt:
                logging.info("Keyboard interrupt received. Shutting down...")
                self.is_running = False
            except Exception as e:
                logging.critical(f"An unhandled exception occurred in the main loop: {e}", exc_info=True)
                # In a real system, implement a backoff strategy before restarting.
                time.sleep(30)

        logging.info("Bridge listener has stopped.")


if __name__ == "__main__":
    # This is the entry point of the script.
    # It sets up the configuration and starts the orchestrator.
    
    # Configuration check
    if not SOURCE_CHAIN_RPC_URL or not BRIDGE_CONTRACT_ADDRESS:
        raise ValueError("Configuration error: Please set SOURCE_CHAIN_RPC_URL and BRIDGE_CONTRACT_ADDRESS in your .env file.")

    app_config = {
        'rpc_url': SOURCE_CHAIN_RPC_URL,
        'contract_address': BRIDGE_CONTRACT_ADDRESS,
        'contract_abi': BRIDGE_CONTRACT_ABI,
        'oracle_endpoint': ORACLE_API_ENDPOINT
    }

    try:
        orchestrator = BridgeOrchestrator(app_config)
        orchestrator.run()
    except RuntimeError as e:
        logging.critical(f"Failed to start the orchestrator: {e}")
    except Exception as e:
        logging.critical(f"A fatal error occurred during initialization: {e}", exc_info=True)

# @-internal-utility-start
def log_event_6335(event_name: str, level: str = "INFO"):
    """Logs a system event - added on 2025-11-09 13:28:22"""
    print(f"[{level}] - 2025-11-09 13:28:22 - Event: {event_name}")
# @-internal-utility-end

