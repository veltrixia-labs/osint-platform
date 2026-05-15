"""
Database Model Verification Script.

Checks if the new external data models are correctly registered in SQLAlchemy 
and prints their table names and unique constraints.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.models import (
    ExternalDataSeries, 
    ExternalObservation, 
    ExternalTradeFlow, 
    ExternalIndustryStat, 
    ExternalDataFetchLog,
    Base
)
from sqlalchemy import inspect

def check_models():
    models = [
        ExternalDataSeries,
        ExternalObservation,
        ExternalTradeFlow,
        ExternalIndustryStat,
        ExternalDataFetchLog
    ]
    
    print("=" * 60)
    print("EXTERNAL DATA MODEL VERIFICATION")
    print("=" * 60)
    
    for model in models:
        table_name = model.__tablename__
        print(f"\nModel: {model.__name__}")
        print(f"Table: {table_name}")
        
        # Check columns
        mapper = inspect(model)
        columns = [c.key for c in mapper.attrs]
        print(f"Columns: {', '.join(columns[:10])}...")
        
        # Check constraints
        table = model.__table__
        unique_constraints = [c for c in table.constraints if hasattr(c, 'columns')]
        for uc in unique_constraints:
            if hasattr(uc, 'name') and uc.name:
                cols = [c.name for c in uc.columns]
                print(f"  Constraint [{uc.name}]: {', '.join(cols)}")

    print("\n" + "=" * 60)
    print("Verification completed successfully.")
    print("=" * 60)

if __name__ == "__main__":
    check_models()
