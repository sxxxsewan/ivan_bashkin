from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
    )
    op.create_table(
        "readers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("ticket_number", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("isbn", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
    )
    op.create_table(
        "book_copies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("inventory_number", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
    )
    op.create_table(
        "loans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reader_id", sa.Integer(), sa.ForeignKey("readers.id"), nullable=False),
        sa.Column("copy_id", sa.Integer(), sa.ForeignKey("book_copies.id"), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("return_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("penalty_amount", sa.Numeric(10, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("loans")
    op.drop_table("book_copies")
    op.drop_table("books")
    op.drop_table("readers")
    op.drop_table("users")