
import asyncio
import os
import aiohttp
import json
from src.wallet.wallet_manager import WalletManager
from web3 import Web3

# 0x API (No key needed for low rate, or use public)
ZERO_EX_URL = "https://polygon.api.0x.org/swap/v1/quote"

NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
BRIDGED_USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

async def auto_swap():
    wm = WalletManager()
    print(f"Swap Wallet: {wm.address}")
    
    # Check Native Balance
    web3 = wm.web3_polygon
    abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
           {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"success","type":"bool"}],"type":"function"}]
    
    ctr = web3.eth.contract(address=web3.to_checksum_address(NATIVE_USDC), abi=abi)
    bal_wei = ctr.functions.balanceOf(wm.address).call()
    bal_usdc = bal_wei / 1e6
    
    print(f"Native USDC Balance: ${bal_usdc:.2f}")
    
    if bal_usdc < 1.0:
        print("❌ Balance too low to swap.")
        return

    # Use 99% of balance to leave dust? Or max? 0x handles partial?
    # Let's swap ALL.
    print(f"[INFO] Fetching Swap Quote for {bal_usdc} USDC -> USDC.e...")
    
    params = {
        "sellToken": NATIVE_USDC,
        "buyToken": BRIDGED_USDC,
        "sellAmount": str(bal_wei),
        "takerAddress": wm.address
    }
    
    headers = {"0x-api-key": "c928c057-7619-4008-8e67-C928C0577619"} 
    
    async with aiohttp.ClientSession() as session:
        async with session.get(ZERO_EX_URL, params=params, headers=headers) as resp:
            if resp.status != 200:
                print(f"[ERROR] 0x API Error: {await resp.text()}")
                return
            
            quote = await resp.json()
            
    # Check Approval
    allowance_target = quote['allowanceTarget']
    
    print(f"[INFO] Approving 0x Proxy ({allowance_target})...")
    # Build Approve Tx
    approve_tx = ctr.functions.approve(
        web3.to_checksum_address(allowance_target),
        int(bal_wei)
    ).build_transaction({
        'from': wm.address,
        'nonce': web3.eth.get_transaction_count(wm.address),
        'gasPrice': web3.eth.gas_price
    })
    
    # Sign & Send Approve
    tx_hash = wm.send_transaction(approve_tx)
    print(f"[OK] Approve Sent: {web3.to_hex(tx_hash)}")
    wm.wait_for_receipt(tx_hash)
    
    # Execute Swap
    print("[INFO] Executing Swap...")
    tx_data = quote['data']
    to_addr = quote['to']
    value = int(quote['value'])
    gas = int(quote['estimatedGas'])
    
    swap_tx = {
        'from': wm.address,
        'to': web3.to_checksum_address(to_addr),
        'data': tx_data,
        'value': value,
        'gas': int(gas * 1.5), # Buffer
        'gasPrice': web3.eth.gas_price,
        'nonce': web3.eth.get_transaction_count(wm.address)
    }
    
    tx_hash_swap = wm.send_transaction(swap_tx)
    print(f"[OK] Swap Sent: {web3.to_hex(tx_hash_swap)}") 

if __name__ == "__main__":
    asyncio.run(auto_swap())
