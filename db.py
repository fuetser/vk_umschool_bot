from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


engine = create_engine("sqlite:///db.db")
Session = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    city = Column(String)

    def __init__(self, user_id, city):
        self.user_id = user_id
        self.city = city

    def __repr__(self):
        return f"<User({self.user_id}, {self.city})>"


if __name__ == '__main__':
    Base.metadata.create_all(engine)
