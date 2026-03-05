"""create ingestion_jobs table

Revision ID: 028_ingestion_jobs
Revises: 027_cron_job_config
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "028_ingestion_jobs"
down_revision: Union[str, None] = "027_cron_job_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("job_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_jobs_id"), "ingestion_jobs", ["id"], unique=False)
    op.create_index(op.f("ix_ingestion_jobs_created_at"), "ingestion_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_ingestion_jobs_job_type"), "ingestion_jobs", ["job_type"], unique=False)
    op.create_index(op.f("ix_ingestion_jobs_status"), "ingestion_jobs", ["status"], unique=False)
    op.create_index(
        op.f("ix_ingestion_jobs_celery_task_id"), "ingestion_jobs", ["celery_task_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_jobs_celery_task_id"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_status"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_job_type"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_created_at"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")

