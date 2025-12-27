
from src.wallet.wallet_manager import WalletManager
from web3 import Web3

def check_native():
    wm = WalletManager()
    web3 = wm.web3_polygon
    
    # Native USDC (Circle)
    native_addr = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    
    abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]
    
    ctr = web3.eth.contract(address=web3.to_checksum_address(native_addr), abi=abi)
    bal = ctr.functions.balanceOf(wm.address).call()
    
    print(f"Native USDC Balance: {bal/1e6}")

if __name__ == "__main__":
    check_native()
