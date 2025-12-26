import os
import json
from web3 import Web3
from src.wallet.wallet_manager import WalletManager

# Polymarket CTF Address on Polygon
CTF_EXCHANGE_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACE5EA0476045"
# Polymarket uses Bridged USDC (USDC.e) on Polygon PoS usually, checking config...
# Defaulting to the one in WalletManager

class AtomicExecutor:
    """
    Executes atomic arbitrage transactions on the Gnosis Conditional Tokens Framework (CTF).
    Handles 'splitPosition' (Mint) and 'mergePositions' (Redeem).
    """
    
    def __init__(self, wallet_manager: WalletManager):
        self.wallet = wallet_manager
        self.web3 = self.wallet.web3_polygon
        self.ctf_address = self.web3.to_checksum_address(CTF_EXCHANGE_ADDRESS)
        
        # Minimum ABI for split/merge
        self.ctf_abi = [
            {
                "constant": False,
                "inputs": [
                    {"name": "collateralToken", "type": "address"},
                    {"name": "parentCollectionId", "type": "bytes32"},
                    {"name": "conditionId", "type": "bytes32"},
                    {"name": "partition", "type": "uint256[]"},
                    {"name": "amount", "type": "uint256"}
                ],
                "name": "splitPosition",
                "outputs": [],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [
                    {"name": "collateralToken", "type": "address"},
                    {"name": "parentCollectionId", "type": "bytes32"},
                    {"name": "conditionId", "type": "bytes32"},
                    {"name": "partition", "type": "uint256[]"},
                    {"name": "amount", "type": "uint256"}
                ],
                "name": "mergePositions",
                "outputs": [],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        
        self.contract = self.web3.eth.contract(address=self.ctf_address, abi=self.ctf_abi)
        
    def get_parent_collection_id(self):
        # Usually bytes32(0) for base markets
        return "0x" + "0" * 64
        
    def get_partition(self):
        # [1, 2] for binary markets (Yes/No)
        return [1, 2]

    async def execute_split(self, condition_id, amount_usdc):
        """
        Mint YES + NO tokens from USDC.
        amount_usdc: Amount in USDC units (e.g. 10.5)
        """
        try:
            # Convert amount to wei (6 decimals for USDC)
            amount_wei = int(amount_usdc * 1e6)
            
            parent_collection_id = self.get_parent_collection_id()
            partition = self.get_partition()
            
            # Ensure condition_id is bytes32
            if not condition_id.startswith("0x"):
                condition_id = "0x" + condition_id
                
            # Need USDC contract address from wallet manager
            usdc_address = self.wallet.address  # Placeholder, should fetch from config
            # TODO: Add collateral token address correctly
            
            print(f"🔄 Executing SPLIT (Mint) for {amount_usdc} USDC...")
            
            # Construct transaction
            tx = self.contract.functions.splitPosition(
                "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", # USDC.e
                parent_collection_id,
                condition_id,
                partition,
                amount_wei
            ).build_transaction({
                'from': self.wallet.address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet.address),
            })
            
            # Sign and send
            tx_hash = self.wallet.send_transaction(tx, network="polygon")
            print(f"✅ Split Transaction sent: https://polygonscan.com/tx/{self.web3.to_hex(tx_hash)}")
            return tx_hash
            
        except Exception as e:
            print(f"❌ Split Execution Failed: {e}")
            return None

    async def execute_merge(self, condition_id, amount_tokens):
        """
        Redeem USDC from YES + NO tokens.
        amount_tokens: Amount of tokens to merge (must have equal amount of YES and NO)
        """
        try:
            amount_wei = int(amount_tokens * 1e6)
            parent_collection_id = self.get_parent_collection_id()
            partition = self.get_partition()
            
            if not condition_id.startswith("0x"):
                condition_id = "0x" + condition_id
                
            print(f"🔄 Executing MERGE (Redeem) for {amount_tokens} tokens...")
            
            tx = self.contract.functions.mergePositions(
                "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", # USDC.e
                parent_collection_id,
                condition_id,
                partition,
                amount_wei
            ).build_transaction({
                'from': self.wallet.address,
                'nonce': self.web3.eth.get_transaction_count(self.wallet.address),
            })
            
            tx_hash = self.wallet.send_transaction(tx, network="polygon")
            print(f"✅ Merge Transaction sent: https://polygonscan.com/tx/{self.web3.to_hex(tx_hash)}")
            return tx_hash
            
        except Exception as e:
            print(f"❌ Merge Execution Failed: {e}")
            return None
