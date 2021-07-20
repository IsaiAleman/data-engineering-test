import pandas as pd
import numpy as np
import pymysql
import time
import schedule;
from pymongo import MongoClient
from sqlalchemy import create_engine


def _connect_mongo_source(host, port, username, password, db):
    if username and password:
        mongo_uri = 'mongodb://%s:%s@%s:%s/%s' % (username, password, host, port, db)
        conn = MongoClient(mongo_uri)
    else:
        conn = MongoClient(host, port)


    return conn[db]


def _connect_sql_source(host, port, username, password, db):
    mysql_uri = 'mysql+pymysql://%s:%s@%s:%s/%s' % (username, password, host, port, db)
    sqlEngine = create_engine(mysql_uri, pool_recycle=3600)

    return sqlEngine.connect()

def extract_from_mongo(db, collection, host='localhost', port=27017, username=None, password=None, no_id=True):
    db = _connect_mongo_source(host=host, port=port, username=username, password=password, db=db)

    pipeline = [
      {"$unwind": {"path": "$items_data","preserveNullAndEmptyArrays": True }},
      {"$match": {"$expr": { "$and": [
        { "$gt": [ "$createdAt", { "$subtract": [ "$$NOW", 24 * 60 * 60 * 1000] } ] },
        { "$lt": [ "$createdAt", "$$NOW" ] } ] } } }
      ]

    cursor = db[collection].aggregate(pipeline)
   
    normalized = pd.json_normalize(list(cursor))
    df =  pd.DataFrame(normalized)

    if no_id:
        del df['_id']

    return df


def extract_from_sql(db, host='localhost', port=3306, username=None, password=None, no_id=True):
  sqlEngine = _connect_sql_source(host=host, port=port, username=username, password=password, db=db)
  dbConnection = sqlEngine.connect()
  df = pd.read_sql('SELECT ib.ordernumber, c.id as customerid, i.id as itemid, c.firstname, c.lastname, c.phonenumber, c.address, '
                    + 'c.curp , c.rfc, i.name, i.price as itemprice, ib.price as orderprice, ib.comments, ib.createdAt '
                    + 'FROM Items_Bought ib '
                    + 'INNER JOIN Customers c ON c.id = ib.customerid '
                    + 'INNER JOIN Items i ON i.id = ib.itemid '
                    + 'WHERE ib.createdAt < NOW() AND ib.createdAt > DATE_SUB(NOW(), INTERVAL 1 DAY);', dbConnection)
  pd.set_option('display.expand_frame_repr', False)

  return df


def transform_sql_source(df): 
  incoming_data = {
    'fullname':[],
    'orderprice':[],
    'itemname': [],
    'date': [],
    'origin': [],
  }

  df["fullname"] = df["firstname"] + ' ' + df["lastname"]
  
  incoming_data['fullname'] = df["fullname"].tolist()
  incoming_data['orderprice'] = df["orderprice"].tolist()
  incoming_data['itemname'] = df["name"].tolist()
  incoming_data['date'] = df["createdAt"].tolist()
  incoming_data['origin'] = df["origin"].tolist()

  return pd.DataFrame(incoming_data)

def transform_mongo_source(df):
  incoming_data = {
    'fullname':[],
    'orderprice':[],
    'itemname': [],
    'date': [],
    'origin': [],
  }

  df["fullname"] = df["firstname"] + ' ' + df["lastname"]
  
  incoming_data['fullname'] = df["fullname"].tolist()
  incoming_data['orderprice'] = df["items_data.price"].tolist()
  incoming_data['itemname'] = df["items_data.title"].tolist()
  incoming_data['date'] = df["createdAt"].tolist()
  incoming_data['origin'] = df["origin"].tolist()

  return pd.DataFrame(incoming_data)

def etl_pipeline():

  # extract
  df_sql = extract_from_sql('test', host='127.0.0.1', port=3306, username='root', password='password')
  df_mongo = extract_from_mongo('test', 'bought_items')
  df_sql['origin'] = 'sql'
  df_mongo['origin'] = 'mongo'


  incoming_data = { 'fullname':[], 'orderprice':[], 'itemname': [], 'date': [],'origin': [] }
  
  # transform
  df_sql = transform_sql_source(df_sql)
  df_mongo = transform_mongo_source(df_mongo)
  df = pd.DataFrame(incoming_data)
  df = df.append(df_sql)
  df = df.append(df_mongo)

  #load
  sql_engine = _connect_sql_source(host='127.0.0.1', port=3306, username='root', password='password', db='dwh')
  db_dwh_connection = sql_engine.connect()
  df.to_sql('orders', db_dwh_connection, if_exists='append', index=False)
  db_dwh_connection.close()
  

def main():
  schedule.every().day.at("12:00").do(etl_pipeline)
  while 1:
    schedule.run_pending()
    time.sleep(1)

main()