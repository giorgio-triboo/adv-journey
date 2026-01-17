from flask import Flask, render_template, jsonify, request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime
import json

app = Flask(__name__)

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@db:5432/cepudb')
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_table_names():
    """Get all table names from the database"""
    inspector = inspect(engine)
    return inspector.get_table_names()

def get_table_columns(table_name):
    """Get column information for a table"""
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    return [{'name': col['name'], 'type': str(col['type']), 'nullable': col['nullable']} for col in columns]

def get_table_data(table_name, page=1, per_page=100, search=None):
    """Get paginated data from a table"""
    db = SessionLocal()
    try:
        # Build query
        query = f"SELECT * FROM {table_name}"
        params = {}
        
        if search:
            # Get columns to search in
            columns = get_table_columns(table_name)
            search_conditions = []
            for col in columns:
                if col['type'].startswith('VARCHAR') or col['type'].startswith('TEXT') or col['type'].startswith('CHAR'):
                    search_conditions.append(f"{col['name']}::text ILIKE :search")
            if search_conditions:
                query += " WHERE " + " OR ".join(search_conditions)
                params['search'] = f"%{search}%"
        
        # Count total
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        if search and search_conditions:
            count_query += " WHERE " + " OR ".join(search_conditions)
        
        total = db.execute(text(count_query), params).scalar()
        
        # Get paginated data
        offset = (page - 1) * per_page
        query += f" ORDER BY id DESC LIMIT :limit OFFSET :offset"
        params['limit'] = per_page
        params['offset'] = offset
        
        result = db.execute(text(query), params)
        rows = result.fetchall()
        
        # Convert to list of dicts
        columns = [col for col in result.keys()]
        data = [dict(zip(columns, row)) for row in rows]
        
        # Format datetime and JSON fields
        for row in data:
            for key, value in row.items():
                if isinstance(value, datetime):
                    row[key] = value.isoformat()
                elif isinstance(value, (dict, list)):
                    row[key] = json.dumps(value, ensure_ascii=False, indent=2)
        
        return {
            'data': data,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        }
    finally:
        db.close()

def get_table_stats(table_name):
    """Get statistics about a table"""
    db = SessionLocal()
    try:
        count = db.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        return {'count': count}
    finally:
        db.close()

@app.route('/')
def index():
    """Main page with table list"""
    tables = get_table_names()
    table_stats = {}
    for table in tables:
        table_stats[table] = get_table_stats(table)
    return render_template('index.html', tables=tables, table_stats=table_stats)

@app.route('/table/<table_name>')
def view_table(table_name):
    """View table data"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    search = request.args.get('search', '')
    
    # Validate table name to prevent SQL injection
    tables = get_table_names()
    if table_name not in tables:
        return "Table not found", 404
    
    columns = get_table_columns(table_name)
    table_data = get_table_data(table_name, page, per_page, search)
    
    return render_template('table.html', 
                         table_name=table_name,
                         columns=columns,
                         data=table_data['data'],
                         pagination=table_data)

@app.route('/api/table/<table_name>')
def api_table(table_name):
    """API endpoint for table data"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    search = request.args.get('search', '')
    
    tables = get_table_names()
    if table_name not in tables:
        return jsonify({'error': 'Table not found'}), 404
    
    table_data = get_table_data(table_name, page, per_page, search)
    return jsonify(table_data)

@app.route('/api/tables')
def api_tables():
    """API endpoint for table list"""
    tables = get_table_names()
    table_stats = {}
    for table in tables:
        table_stats[table] = get_table_stats(table)
    return jsonify({'tables': tables, 'stats': table_stats})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
