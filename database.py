# database.py
import sqlite3
import random

DB_PATH = "carduka_market.db"

def init_and_seed_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Reset table structure cleanly on startup
    cursor.execute("DROP TABLE IF EXISTS historical_sales")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            make TEXT,
            model TEXT,
            year INTEGER,
            mileage INTEGER,
            sale_price REAL,
            condition_grade TEXT
        )
    """)
    
    # 30 entries total: 10 per car model rule
    car_configurations = [
        ("Toyota", "Hilux", 4800000),   # Base benchmark for 2019 Hilux
        ("Mazda", "Axela", 2200000),# Base benchmark for 2019 Vanguard
        ("Toyota", "Premio", 2600000)   # Base benchmark for 2019 Premio
    ]
    
    for make, model, base_benchmark in car_configurations:
        for _ in range(20):
            # Target realistic recent years (2018-2022)
            year = random.choice([2018, 2019, 2020, 2021, 2022])
            mileage = random.randint(30000, 130000)
            condition = random.choice(["Foreign Used", "Locally Used", "New"])
            
            # 1. Year Modifier: Compounding price delta for recent models (~250k-350k per year difference)
            year_delta = (year - 2019) * 300000
            current_price = base_benchmark + year_delta
            
            # 2. Mileage Modifier: Moderate degradation curve
            mileage_deduction = (mileage // 10000) * 45000
            current_price -= mileage_deduction
            
            # 3. Condition Premium/Discount
            if condition == "New":
                current_price += 600000
            elif condition == "Foreign Used":
                current_price += 250000  # Imported quality premium over domestic wear
            elif condition == "Locally Used":
                current_price -= 300000  # Standard local wear discount
                
            # Add a slight marketplace variance noise (+/- 100,000 KSh)
            final_sale_price = current_price + random.randint(-100000, 100000)
            
            # Safety floor constraint so valuations never drop beneath scrap logic
            floor_price = base_benchmark * 0.5
            
            cursor.execute("""
                INSERT INTO historical_sales (make, model, year, mileage, sale_price, condition_grade)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (make, model, year, mileage, max(final_sale_price, floor_price), condition))
            
    conn.commit()
    conn.close()
    print("Database successfully initialized with 30 realistic Kenyan market variants.")

if __name__ == "__main__":
    init_and_seed_db()