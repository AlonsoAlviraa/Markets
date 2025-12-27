import os
from eth_account import Account
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

class WalletManager:
    """
    Manages wallet operations for both Polygon and SX Network.
    Handles private key loading, transaction signing, and balance monitoring.
    """
    
    def __init__(self):
        # Load private key from environment
        self.private_key = os.getenv("PRIVATE_KEY")
        if not self.private_key:
            raise ValueError("PRIVATE_KEY not found in .env file")
        
        # Create account from private key
        self.account = Account.from_key(self.private_key)
        self.address = self.account.address
        
        # Initialize Web3 instances for both networks
        self.polygon_rpc = os.getenv("POLYGON_RPC", "https://polygon-rpc.com")
        self.sx_rpc = os.getenv("SX_RPC", "https://rpc.sx-rollup.gelato.digital")
        
        self.web3_polygon = Web3(Web3.HTTPProvider(self.polygon_rpc))
        self.web3_sx = Web3(Web3.HTTPProvider(self.sx_rpc))
        
        print(f"[OK] Wallet initialized: {self.address}")
        print(f"   Polygon connected: {self.web3_polygon.is_connected()}")
        print(f"   SX Network connected: {self.web3_sx.is_connected()}")
    
    def get_balance(self, network="polygon"):
        """Get USDC balance on specified network"""
        web3 = self.web3_polygon if network == "polygon" else self.web3_sx
        
        # USDC contract addresses
        # USDC contract addresses (Updated with verified addresses)
        usdc_addresses = {
            "polygon": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # Bridged USDC (USDC.e) - Polymarket Standard
            "sx": "0x6629Ce1Cf35Cc1329ebB4F63202F3f197b3F050B"  # USDC on SX Rollup (verified)
        }
        
        usdc_address = usdc_addresses.get(network)
        if not usdc_address:
            return 0
        
        # ERC20 ABI for balanceOf
        abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]
        
        contract = web3.eth.contract(address=web3.to_checksum_address(usdc_address), abi=abi)
        balance = contract.functions.balanceOf(web3.to_checksum_address(self.address)).call()
        
        # USDC has 6 decimals
        return balance / 1e6
    
    def check_gas_balance(self, min_gas=0.1):
        """Check if wallet has enough gas (native tokens) on both networks"""
        try:
            # Check Polygon (POL)
            pol_wei = self.web3_polygon.eth.get_balance(self.address)
            pol_bal = self.web3_polygon.from_wei(pol_wei, 'ether')
            
            # Check SX (SX)
            sx_wei = self.web3_sx.eth.get_balance(self.address)
            sx_bal = self.web3_sx.from_wei(sx_wei, 'ether')
            
            poly_ok = pol_bal >= min_gas
            sx_ok = sx_bal >= min_gas
            
            msg = f"Gas: Polygon {pol_bal:.4f} POL | SX {sx_bal:.4f} SX"
            return poly_ok, sx_ok, msg
            
        except Exception as e:
            return False, False, f"Gas check error: {e}"
    
    def sign_transaction(self, transaction, network="polygon"):
        """Sign a transaction with the wallet's private key"""
        web3 = self.web3_polygon if network == "polygon" else self.web3_sx
        
        # Add nonce and gas parameters
        transaction['nonce'] = web3.eth.get_transaction_count(self.address)
        transaction['from'] = self.address
        
        # Estimate gas if not provided
        if 'gas' not in transaction:
            transaction['gas'] = web3.eth.estimate_gas(transaction)
        
        # Sign the transaction
        signed_txn = web3.eth.account.sign_transaction(transaction, self.private_key)
        return signed_txn
    
    def send_transaction(self, transaction, network="polygon"):
        """Sign and send a transaction"""
        web3 = self.web3_polygon if network == "polygon" else self.web3_sx
        
        signed_txn = self.sign_transaction(transaction, network)
        tx_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
        
        print(f"Transaction sent: {web3.to_hex(tx_hash)}")
        return tx_hash
    
    def wait_for_receipt(self, tx_hash, network="polygon", timeout=120):
        """Wait for transaction confirmation"""
        web3 = self.web3_polygon if network == "polygon" else self.web3_sx
        
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        return receipt

if __name__ == "__main__":
    # Test wallet initialization
    wallet = WalletManager()
    
    print(f"\nBalances:")
    print(f"  Polygon USDC: ${wallet.get_balance('polygon'):.2f}")
    print(f"  SX Network USDC: ${wallet.get_balance('sx'):.2f}")
