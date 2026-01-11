class CrudService:
    def __init__(self, model, db_session):
        self.model = model
        self.db_session = db_session

    def list_all(self):
        return self.model.query.order_by(self.model.created_at.desc()).all()

    def get(self, item_id):
        return self.model.query.get(item_id)

    def create(self, **fields):
        record = self.model(**fields)
        self.db_session.add(record)
        self.db_session.commit()
        return record

    def update(self, record, **fields):
        for key, value in fields.items():
            setattr(record, key, value)
        self.db_session.commit()
        return record

    def delete(self, record):
        self.db_session.delete(record)
        self.db_session.commit()
        return record
