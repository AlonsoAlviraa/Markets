
import asyncio
import time
from src.wallet.wallet_manager import WalletManager
from web3 import Web3

# Uniswap V3 Router (Polygon)
ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
BRIDGED_USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

def swap_v3():
    wm = WalletManager()
    print(f"Swap Wallet: {wm.address}")
    web3 = wm.web3_polygon
    
    # 1. Check Balance
    abi_erc20 = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
                 {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"success","type":"bool"}],"type":"function"}]
    
    ctr_usdc = web3.eth.contract(address=web3.to_checksum_address(NATIVE_USDC), abi=abi_erc20)
    bal_wei = ctr_usdc.functions.balanceOf(wm.address).call()
    bal_usdc = bal_wei / 1e6
    print(f"Native USDC Balance: ${bal_usdc:.2f}")
    
    if bal_usdc < 1.0:
        print("[ERROR] Balance too low.")
        return

    # 2. Approve Router
    print(f"[INFO] Approving Uniswap V3 Router ({ROUTER_ADDRESS})...")
    approve_tx = ctr_usdc.functions.approve(
        web3.to_checksum_address(ROUTER_ADDRESS),
        int(bal_wei)
    ).build_transaction({
        'from': wm.address,
        'nonce': web3.eth.get_transaction_count(wm.address),
        'gasPrice': web3.eth.gas_price
    })
    
    tx_hash = wm.send_transaction(approve_tx)
    print(f"[OK] Approve Sent: {web3.to_hex(tx_hash)}")
    wm.wait_for_receipt(tx_hash)
    
    # 3. Swap (exactInputSingle)
    # ABI for exactInputSingle
    # function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
    # struct ExactInputSingleParams {
    #   address tokenIn; address tokenOut; uint24 fee; address recipient; uint256 deadline; uint256 amountIn; uint256 amountOutMinimum; uint160 sqrtPriceLimitX96;
    # }
    
    router_abi = [{
        "inputs": [{
            "components": [
                {"internalType": "address", "name": "tokenIn", "type": "address"},
                {"internalType": "address", "name": "tokenOut", "type": "address"},
                {"internalType": "uint24", "name": "fee", "type": "uint24"},
                {"internalType": "address", "name": "recipient", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
            ],
            "name": "params",
            "type": "tuple"
        }],
        "name": "exactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    }]
    
    router = web3.eth.contract(address=web3.to_checksum_address(ROUTER_ADDRESS), abi=router_abi)
    
    params = (
        web3.to_checksum_address(NATIVE_USDC),
        web3.to_checksum_address(BRIDGED_USDC),
        500, # Fee 0.05%
        wm.address,
        int(time.time()) + 300, # deadline
        int(bal_wei),
        0, # min out (slippage 100% allowed for simplicity, stable swap usually safe)
        0
    )
    
    print("[INFO] Executing Uniswap V3 Swap...")
    swap_tx = router.functions.exactInputSingle(params).build_transaction({
        'from': wm.address,
        'value': 0,
        'gas': 300000,
        'gasPrice': web3.eth.gas_price,
        'nonce': web3.eth.get_transaction_count(wm.address)
    })
    
    tx_hash_swap = wm.send_transaction(swap_tx)
    print(f"[OK] Swap Sent: {web3.to_hex(tx_hash_swap)}")

if __name__ == "__main__":
    swap_v3()
