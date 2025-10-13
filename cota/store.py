import os
import json
import contextlib
import itertools
import sqlalchemy as sa
from time import sleep
import logging
from typing import Text, List, Optional, Union, Dict, Iterator
from sqlalchemy import or_, and_, func, desc
from cota.dst import DST

logger = logging.getLogger(__name__)

class Store:
    """Class to hold all of the TrackerStore classes"""

    def __init__(
            self,
    ) -> None:
        """Create a TrackerStore."""
        self.max_history = None

    @staticmethod
    def create(endpoint_config: Dict) -> "Store":
        """Factory to create a store"""
        store_type = endpoint_config.get('type', None)
        if not store_type:
            return MemoryStore()

        if store_type.lower() == "sql":
            store = SQLStore(
                dialect = endpoint_config.get('dialect','mysql+pymysql'),
                host = endpoint_config.get('host','127.0.0.1'),
                port = endpoint_config.get('port',3306),
                db = endpoint_config.get('db','mysql'),
                username = endpoint_config.get('username','root'),
                password = endpoint_config.get('password',''),
                query = endpoint_config.get('query',{})
            )
            return store
        return MemoryStore()

    async def save(self, dst: DST) -> None:
        raise NotImplementedError()

    async def retrieve(self, session_id: Text) -> Optional[Dict]:
        raise NotImplementedError()
    
    async def retrieve_conversations(self, user_id: Text):
        raise NotImplementedError()


class MemoryStore(Store):
    """Store tracker data"""

    def __init__(
            self
    ) -> None:
        self.max_history = None
        self.store = list()

    async def save(self, dst: DST) -> None:
        records = [ record for record in self.store if record["session_id"] == dst.session_id ]
        latest_timestamp = -1
        if len(records) > 0:
            #records = sorted(records, key=lambda record: record["timestamp"])
            #latest_timestamp = records[-1]["timestamp"]
            latest_timestamp = max(record["timestamp"] for record in records)

        for action in dst.actions:
            action_dict = action.as_dict()
            timestamp = action_dict.get('timestamp')

            if timestamp > latest_timestamp:
                self.store.append({
                    'session_id': dst.session_id,
                    'sender_id': action_dict.get("sender_id"),
                    'receiver_id': action_dict.get("receiver_id"),
                    'timestamp': timestamp,
                    'action_name': action_dict.get("name"),
                    'data': json.dumps(action_dict),
                })

    async def retrieve(self, session_id: Text) -> List[Dict]:
        """retrive data by session_id"""
        records = [ record for record in self.store if record["session_id"] == session_id ]
        
        if len(records) == 0:
            logger.debug(f"No records found for session id '{session_id}'")
            return None

        actions_dict = [json.loads(record.get('data')) for record in sorted(records, key=lambda record: record["timestamp"])]
        return actions_dict
    
    async def latest_utter(self, session_ids: List[Text]) -> List[Dict]:
        utters = []
        for session_id in session_ids:
            print("session_id: ", session_id)
            records = [record for record in self.store if record["session_id"] == session_id and record["action_name"] in ["Query", "Response"]]
            if records:
                print("records: ", records)
                latest_utter = sorted(records, key=lambda record: record["timestamp"])[-1]
                utters.append(json.loads(latest_utter.get("data")))
        return utters


class SQLStore(Store):
    """Store which can save and retrieve trackers from an SQL database."""

    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()

    class SQLAction(Base):
        """Represents an action in the SQL Tracker Store"""
        __tablename__ = "actions"

        id = sa.Column(sa.Integer, nullable=False, primary_key=True)
        sender_id = sa.Column(sa.String(255), nullable=False, index=True)
        receiver_id = sa.Column(sa.String(255), nullable=False, index=True)
        session_id = sa.Column(sa.String(255), nullable=False, index=True)
        timestamp = sa.Column(sa.String(255), nullable=False)
        action_name = sa.Column(sa.String(255))
        data = sa.Column(sa.Text)

    def __init__(
            self,
            dialect: Text = "sqlite",
            host: Optional[Text] = None,
            port: Optional[int] = None,
            db: Text = "cota.db",
            username: Text = None,
            password: Text = None,
            login_db: Optional[Text] = None,
            query: Optional[Dict] = None,
    ) -> None:
        import sqlalchemy.exc
        engine_url = sa.engine.url.URL(
            dialect,
            username,
            password,
            host,
            port,
            database=login_db if login_db else db,
            query=query,
        )
        logger.debug(f"Attempting to connect to database via '{engine_url}'.")

        # Database might take a while to come up
        while True:
            try:
                self.engine = sa.engine.create_engine(engine_url)

                if login_db:
                    from sqlalchemy import create_engine
                    self._create_database(self.engine, db)
                    engine_url.database = db
                    self.engine = create_engine(engine_url)
                try:
                    self.Base.metadata.create_all(self.engine)
                except (
                        sqlalchemy.exc.OperationalError,
                        sqlalchemy.exc.ProgrammingError,
                ) as e:
                    logger.error(f"Could not create tables: {e}")

                self.sessionmaker = sa.orm.session.sessionmaker(bind=self.engine)
                break
            except (
                    sqlalchemy.exc.OperationalError,
                    sqlalchemy.exc.IntegrityError,
            ) as error:
                logger.warning(error)
                sleep(5)

        logger.debug(f"Connection to SQL database '{db}' successful.")
        super().__init__()

    @staticmethod
    def _create_database(engine: "Engine", db: Text):
        """Create database `db` on `engine` if it does not exist."""

        import psycopg2

        conn = engine.connect()

        cursor = conn.connection.cursor()
        cursor.execute("COMMIT")
        cursor.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{db}'")
        exists = cursor.fetchone()
        if not exists:
            try:
                cursor.execute(f"CREATE DATABASE {db}")
            except psycopg2.IntegrityError as e:
                logger.error(f"Could not create database '{db}': {e}")

        cursor.close()
        conn.close()

    async def save(self, tracker: DST) -> None:
        with self.sessionmaker() as session:
            action_num = session.query(self.SQLAction).filter(
                self.SQLAction.session_id == tracker.session_id
            ).order_by(self.SQLAction.timestamp).count()

            for i in range(action_num, len(tracker.actions)):
                action = tracker.actions[i]
                data = action.as_dict()
                sender_id = action.sender_id
                receiver_id = action.receiver_id
                session_id = tracker.session_id
                timestamp = data.get("timestamp")
                action_name = data.get("name")

                # noinspection PyArgumentList
                session.add(
                    self.SQLAction(
                        sender_id=sender_id,
                        receiver_id=receiver_id,
                        session_id=session_id,
                        timestamp=str(timestamp),
                        action_name=action_name,
                        data=json.dumps(data),
                    )
                )
            session.commit()

        logger.debug(f"Tracker with session_id '{tracker.session_id}' stored to database")

    async def retrieve(self, session_id: Text) -> Optional[Dict]:
        """Create a tracker from all previously stored actions."""

        with self.sessionmaker() as session:
            serialised_actions = session.query(self.SQLAction).filter(
                    self.SQLAction.session_id == session_id
                ).order_by(self.SQLAction.timestamp).all()

            actions_dict = [json.loads(action.data) for action in serialised_actions]

            if len(actions_dict) > 0:
                logger.debug(f"Retrun actions dict from session id '{session_id}'")

                return actions_dict
            else:
                logger.debug( f"Can't retrieve session id '{session_id}' from SQL storage. ")
                return None

    async def latest_utter(self, session_ids: List[Text]) -> List[Dict]:
        utters = []
        with self.sessionmaker() as session:
            subquery = (
            session.query(
                self.SQLAction.session_id,
                func.max(self.SQLAction.timestamp).label("max_timestamp")
            )
            .filter(
                self.SQLAction.session_id.in_(session_ids),
                self.SQLAction.action_name.in_(["Query", "Response"])
            )
            .group_by(self.SQLAction.session_id)
            .subquery()
            )

            query = (
            session.query(self.SQLAction.data)
            .join(
                subquery,
                and_(
                    self.SQLAction.session_id == subquery.c.session_id,
                    self.SQLAction.timestamp == subquery.c.max_timestamp
                )
            )
            .order_by(desc(self.SQLAction.timestamp))
            )

            for row in query:
                utters.append(json.loads(row.data))
        return utters