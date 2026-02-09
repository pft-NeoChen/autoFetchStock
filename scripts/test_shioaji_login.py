import os
import shioaji as sj
from dotenv import load_dotenv

def run_test(mode_name, api_key, secret_key, cert_path, cert_password, person_id, is_simulation):
    print(f"\n--- 開始測試 {mode_name} (Simulation: {is_simulation}) ---")
    
    if not api_key or not secret_key:
        print(f"Skipping {mode_name}: API Key or Secret not set in config.env")
        return False

    api = sj.Shioaji(simulation=is_simulation)
    success = False
    
    try:
        # 1. Login
        accounts = api.login(api_key, secret_key)
        print(f"Login successful! Accounts found: {len(accounts)}")
        for acc in accounts:
            print(f" - {acc}")

        # 2. Activate CA
        if cert_path and os.path.exists(cert_path):
            print(f"Activating CA from: {cert_path}")
            api.activate_ca(cert_path, cert_password, person_id)
            print("CA activation successful!")
        else:
            print("Skipping CA activation (cert_path not found).")
            
        # 3. Simple Contract Test
        contract = api.Contracts.Stocks["2330"]
        if contract:
            print(f"Contract test successful: {contract.name}")
            success = True
        else:
            print("Contract test failed.")
            
    except Exception as e:
        print(f"Test FAILED: {str(e)}")
    finally:
        api.logout()
    
    return success

def main():
    load_dotenv("config.env")
    
    cert_path = os.getenv("SHIOAJI_CERT_PATH")
    cert_password = os.getenv("SHIOAJI_CERT_PASSWORD")
    person_id = os.getenv("SHIOAJI_PERSON_ID")

    # Test Simulation
    sim_success = run_test(
        "模擬環境",
        os.getenv("SHIOAJI_API_KEY_SIM"),
        os.getenv("SHIOAJI_SECRET_KEY_SIM"),
        cert_path, cert_password, person_id,
        is_simulation=True
    )

    # Test Production
    prod_success = run_test(
        "正式環境",
        os.getenv("SHIOAJI_API_KEY_PROD"),
        os.getenv("SHIOAJI_SECRET_KEY_PROD"),
        cert_path, cert_password, person_id,
        is_simulation=False
    )

    print("\n" + "="*30)
    print(f"模擬環境測試結果: {'PASS' if sim_success else 'FAIL'}")
    print(f"正式環境測試結果: {'PASS' if prod_success else 'FAIL'}")
    print("="*30)

if __name__ == "__main__":
    main()