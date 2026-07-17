"""initial schema: all prop-threader tables.

Revision ID: 0001
Revises:
Create Date: 2026-07-17 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by alembic
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """create all application tables in dependency order."""
    # 1. groups (no foreign key dependencies)
    op.create_table(
        "groups",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("display_title", sa.String(512), nullable=False),
        sa.Column("normalized_title", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "channel_id", "normalized_title", name="uq_group_identity"),
    )

    # 2. drafts (no foreign key dependencies)
    op.create_table(
        "drafts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "channel_id", "user_id", name="uq_draft_identity"),
    )

    # 3. channel_leases (no foreign key dependencies)
    op.create_table(
        "channel_leases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("owner_user_id", sa.String(255), nullable=False),
        sa.Column("lease_token", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "channel_id", name="uq_channel_lease"),
    )

    # 4. batches (foreign key: groups.id)
    op.create_table(
        "batches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("submitter_user_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batch_workspace_channel", "batches", ["workspace_id", "channel_id"])

    # 5. batch_assets (foreign key: batches.id)
    op.create_table(
        "batch_assets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("asset_details_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("entity_id > 0", name="ck_batch_asset_entity_id_positive"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "entity_id", name="uq_batch_asset_entity"),
    )
    op.create_index("ix_batch_asset_batch", "batch_assets", ["batch_id"])

    # 6. messages (foreign keys: groups.id, batches.id)
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("asset_entity_id", sa.Integer(), nullable=True),
        sa.Column("slack_ts", sa.String(64), nullable=False),
        sa.Column("permalink", sa.String(2048), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False),
        sa.Column("canvas_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_editor_id", sa.String(255), nullable=True),
        sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_latest_group_summary", "messages", ["group_id", "kind", "is_latest"])
    op.create_index(
        "ix_message_latest_asset_root",
        "messages",
        ["workspace_id", "channel_id", "asset_entity_id", "kind", "is_latest"],
    )
    op.create_index(
        "uq_message_latest_group_summary",
        "messages",
        ["group_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'group_summary' AND is_latest = 1"),
        postgresql_where=sa.text("kind = 'group_summary' AND is_latest = true"),
    )
    op.create_index(
        "uq_message_latest_asset_root",
        "messages",
        ["workspace_id", "channel_id", "asset_entity_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'asset_root' AND is_latest = 1"),
        postgresql_where=sa.text("kind = 'asset_root' AND is_latest = true"),
    )

    # 7. operations (foreign key: batches.id)
    op.create_table(
        "operations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("asset_entity_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_safe_error", sa.String(1024), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "kind", "asset_entity_id", name="uq_operation_idempotency"),
    )


def downgrade() -> None:
    """drop all application tables in reverse dependency order."""
    # 7. operations
    op.drop_table("operations")
    # 6. messages
    op.drop_index("uq_message_latest_asset_root", table_name="messages")
    op.drop_index("uq_message_latest_group_summary", table_name="messages")
    op.drop_index("ix_message_latest_asset_root", table_name="messages")
    op.drop_index("ix_message_latest_group_summary", table_name="messages")
    op.drop_table("messages")
    # 5. batch_assets
    op.drop_index("ix_batch_asset_batch", table_name="batch_assets")
    op.drop_table("batch_assets")
    # 4. batches
    op.drop_index("ix_batch_workspace_channel", table_name="batches")
    op.drop_table("batches")
    # 3. channel_leases
    op.drop_table("channel_leases")
    # 2. drafts
    op.drop_table("drafts")
    # 1. groups
    op.drop_table("groups")
