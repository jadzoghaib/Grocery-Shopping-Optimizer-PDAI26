import requests
import pandas as pd
import json
import time

API_URL = "https://tienda.mercadona.es/api/categories/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

COOKIES = {
    "postalCode": "08172" 
}

def get_categories(url=API_URL):
    try:
        response = requests.get(url, headers=HEADERS, cookies=COOKIES)
        response.raise_for_status()
        return response.json().get('results', [])
    except Exception as e:
        print(f"Error fetching categories: {e}")
        return []

def get_category_details(url_or_id):
    if str(url_or_id).startswith("http"):
        url = url_or_id
    else:
        url = f"{API_URL}{url_or_id}"
    try:
        response = requests.get(url, headers=HEADERS, cookies=COOKIES)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching {url_or_id}: {e}")
        return None

def extract_products(category_data):
    products = []
    if not category_data:
        return []
    
    # Check if this category has subcategories or products inside 'categories'
    if 'categories' in category_data:
        for cat in category_data['categories']:
             # Recursively get products from subcategories if structure is nested
             # But usually detailed category endpoint returns products directly in 'products' list of sub-categories
             products.extend(extract_products(cat))
    
    if 'products' in category_data:
        for product in category_data['products']:
            try:
                price_info = product.get('price_instructions', {})
                unit_price = price_info.get('unit_price')
                bulk_price = price_info.get('bulk_price')
                
                # Check format of price
                price = unit_price if unit_price else bulk_price
                
                products.append({
                    'id': product.get('id'),
                    'name': product.get('display_name'),
                    'price': float(price) if price else 0.0,
                    'unit': price_info.get('reference_format', 'unit'), # kg, l, etc.
                    'category': category_data.get('name'),
                    'url': product.get('share_url', f"https://tienda.mercadona.es/product/{product.get('id')}/")
                })
            except Exception as e:
                continue

    return products

def main():
    print("Fetching top-level categories...")
    # Add trailing slash just in case
    top_categories = get_categories(API_URL + "?lang=es")
    
    if not top_categories:
        print("No top level categories found. Trying without query params.")
        top_categories = get_categories(API_URL)
        
    if top_categories:
        print(f"Sample category data: {json.dumps(top_categories[0], indent=2)}")

    all_products = []
    
    # Limit to a few main categories to avoid scraping thousands if not needed, 
    # but user wants real data so let's aim for breadth.
    # We will process ALL top-level categories but limit depth or number of products per category if needed.
    for cat in top_categories:
        cat_id = cat.get('id')
        print(f"Processing category: {cat.get('name')} (ID: {cat_id})")
        
        # Check for subcategories in the top-level response
        subcats = cat.get('categories', [])
        if subcats:
            print(f"  Found {len(subcats)} subcategories directly. Iterating them...")
            for sub in subcats:
                sub_id = sub.get('id')
                print(f"    Sub-category: {sub.get('name')} (ID: {sub_id})")
                
                # Fetch details for SUB-category
                detail_url = f"{API_URL}{sub_id}/"
                details = get_category_details(detail_url)
                if not details:
                     # Try without trailing slash
                     detail_url = f"{API_URL}{sub_id}"
                     details = get_category_details(detail_url)
                
                if details:
                    products = extract_products(details)
                    print(f"    Found {len(products)} products in sub-category.")
                    all_products.extend(products)
                else:
                    print(f"    Failed to get details for sub-category {sub_id}")
                
                time.sleep(0.5)

        else:
             # Fallback if no subcategories exist
             detail_url = f"{API_URL}{cat_id}/" 
             details = get_category_details(detail_url)
             if details:
                 products = extract_products(details)
                 all_products.extend(products)
        
        time.sleep(0.5) # Be polite
        
    print(f"Total products found: {len(all_products)}")
    
    if all_products:
        df = pd.DataFrame(all_products)
        df.to_csv('mercadona_prices.csv', index=False)
        print("Saved to mercadona_prices.csv")
    else:
        print("No products found.")

if __name__ == "__main__":
    main()
