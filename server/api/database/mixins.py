"""Database module, including the SQLAlchemy database object and DB-related utilities.
from: https://github.com/sloria/cookiecutter-flask/
"""
import operator
from datetime import datetime

import sqlalchemy
import werkzeug

from server.api.database import db
from server.consts import DATE_FORMAT, MAXIMUM_PER_PAGE

# Alias common SQLAlchemy names
Column = db.Column
relationship = db.relationship


class CRUDMixin(object):
    """Mixin that adds convenience methods for CRUD (create, read, update, delete) operations."""

    @classmethod
    def create(cls, **kwargs):
        """Create a new record and save it the database."""
        instance = cls(**kwargs)
        return instance.save()

    def update(self, commit=True, **kwargs):
        """Update specific fields of a record."""
        for attr, value in kwargs.items():
            setattr(self, attr, value)
        return commit and self.save() or self

    def save(self, commit=True):
        """Save the record."""
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def delete(self, commit=True):
        """Remove the record from the database."""
        db.session.delete(self)
        return commit and db.session.commit()


class Model(CRUDMixin, db.Model):
    """Base model class that includes CRUD convenience methods."""

    __abstract__ = True
    default_sort_column = "created_at"
    default_sort_method = "asc"
    ALLOWED_FILTERS = []

    @staticmethod
    def _handle_special_cases(
        column: str, value: str, custom_date: callable = None
    ) -> str:
        """handle special filter cases such bool value or date value"""
        if column == "created_at" or "date" in column and value != None:
            if custom_date:
                value = custom_date(value)
            else:
                value = datetime.strptime(value, DATE_FORMAT)

        if value == "true":
            value = True
        elif value == "false":
            value = False

        return value

    @classmethod
    def _filter_data(
        cls, column: str, filter_: str, custom_date: callable = None
    ) -> sqlalchemy.sql.elements.BinaryExpression:
        """get column and filter strings and return filtering function
        e.g get id=lt:200
        return operator.lt(Model.id, 200)
        NOTE: to compare dates, there must be an operator -
        date=eq:DATE"""
        fields = str(filter_).split(":", 1)
        operators = {
            "le": operator.le,
            "ge": operator.ge,
            "eq": operator.eq,
            "lt": operator.lt,
            "gt": operator.gt,
            "ne": operator.ne,
        }

        method = "eq"
        value_to_compare = filter_
        if len(fields) == 2:
            method = fields[0]
            value_to_compare = fields[1]
        if fields[0] not in operators.keys():
            method = "eq"

        value_to_compare = cls._handle_special_cases(
            column, value_to_compare, custom_date
        )

        try:
            return operators[method](getattr(cls, column), value_to_compare)
        except AttributeError:
            return None

    @classmethod
    def _sort_data(cls, args: werkzeug.datastructures.MultiDict):
        """ get arguments and return order_by function.
        e.g get order_by=date desc
        return cls.date.asc()
        """
        order_by_args = args.get("order_by", "").split()
        try:
            column = order_by_args[0]
            method = order_by_args[1]
        except IndexError:
            column = cls.default_sort_column
            method = cls.default_sort_method

        try:
            return getattr(getattr(cls, column), method)()
        except AttributeError:  # column does not exist
            return getattr(
                getattr(cls, cls.default_sort_column), cls.default_sort_method
            )()

    @classmethod
    def filter_and_sort(
        cls,
        args: werkzeug.datastructures.MultiDict,
        query=None,
        with_pagination: bool = False,
        custom_date: callable = None,
        extra_filters: dict = None,
    ):
        """allow filtering by student, date, lesson_number
        eg. ?limit=20&page=2&student=1&date=lt:2019-01-20T13:20Z&lesson_number=lte:5"""
        filters = {k: v for k, v in args.items() if k in cls.ALLOWED_FILTERS}
        query = query or cls.query
        query = (
            cls._handle_extra_filters(query, args, extra_filters)
            if extra_filters
            else query
        )
        for column, filter_ in filters.items():
            query = query.filter(cls._filter_data(column, filter_, custom_date))
        order_by = cls._sort_data(args)

        query = query.order_by(order_by)
        if "limit" in args and with_pagination:
            page = int(args.get("page", 1))
            limit = min(int(args.get("limit", 20)), MAXIMUM_PER_PAGE)
            return query.paginate(page, limit)
        return query.all()

    @classmethod
    def _handle_extra_filters(
        cls, query, args: werkzeug.datastructures.MultiDict, extra_filters: dict
    ):
        for model, filters in extra_filters.items():
            for key, value in args.items():
                if key in filters:
                    query = query.join(
                        getattr(cls, model.__name__.lower()), aliased=True
                    ).filter(getattr(model, key).like(f"%{value}%"))

        return query


# From Mike Bayer's "Building the app" talk
# https://speakerdeck.com/zzzeek/building-the-app
class SurrogatePK(object):
    """A mixin that adds a surrogate integer 'primary key' column named ``id`` to any declarative-mapped class."""

    __table_args__ = {"extend_existing": True}

    id = Column(db.Integer, primary_key=True)

    @classmethod
    def get_by_id(cls, record_id):
        """Get record by ID."""
        if any(
            (
                isinstance(record_id, (str, bytes)) and record_id.isdigit(),
                isinstance(record_id, (int, float)),
            )
        ):
            return cls.query.get(int(record_id))
        return None


def reference_col(tablename, nullable=False, pk_name="id", **kwargs):
    """Column that adds primary key foreign key reference.
    Usage: ::
        category_id = reference_col('category')
        category = relationship('Category', backref='categories')
    """
    return Column(
        db.ForeignKey("{0}.{1}".format(tablename, pk_name)), nullable=nullable, **kwargs
    )
