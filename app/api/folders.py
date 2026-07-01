from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.folder import Folder

router = APIRouter()


class FolderCreate(BaseModel):
    name: str
    colour: Optional[str] = "#6366f1"


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    colour: Optional[str] = None


@router.get("")
async def list_folders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Folder).order_by(Folder.created_at.asc()))
    return result.scalars().all()


@router.post("")
async def create_folder(data: FolderCreate, db: AsyncSession = Depends(get_db)):
    folder = Folder(name=data.name, colour=data.colour)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.patch("/{folder_id}")
async def update_folder(
    folder_id: str,
    update: FolderUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    for field, value in update.model_dump(exclude_none=True).items():
        setattr(folder, field, value)

    await db.commit()
    await db.refresh(folder)
    return folder


@router.delete("/{folder_id}")
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    await db.delete(folder)
    await db.commit()
    return {"message": "Folder deleted"}
