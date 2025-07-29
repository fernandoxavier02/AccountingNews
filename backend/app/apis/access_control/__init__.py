"""
API for managing email-based access control.
Provides endpoints for checking authorization and managing authorized users.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from app.auth import AuthorizedUser
from app.libs.email_authorization import email_auth
from app.libs.access_middleware import verify_email_authorization, require_admin_access

router = APIRouter(prefix="/access-control")


class AuthorizationCheckRequest(BaseModel):
    email: EmailStr


class AuthorizationCheckResponse(BaseModel):
    email: str
    is_authorized: bool
    is_admin: bool
    authorization_type: Optional[str]
    domain: str
    message: str


class AddEmailRequest(BaseModel):
    email: EmailStr


class AddDomainRequest(BaseModel):
    domain: str


class EmailListResponse(BaseModel):
    authorized_emails: List[str]
    authorized_domains: List[str]


class OperationResponse(BaseModel):
    success: bool
    message: str


@router.get("/check-my-access")
async def check_my_access(user: AuthorizedUser) -> AuthorizationCheckResponse:
    """
    Check the current user's access authorization.
    
    Returns:
        AuthorizationCheckResponse: User's authorization details
    """
    # Verify email authorization
    user = verify_email_authorization(user)
    
    user_email = getattr(user, 'email', None)
    user_sub = getattr(user, 'sub', None)
    
    # Handle case where user doesn't have email (temporary fix for Fernando)
    if not user_email and user_sub == "6a7b599d-bd37-4a57-b92f-f95715e8c332":
        return AuthorizationCheckResponse(
            email="fernandocostaxavier@gmail.com",  # Use the known email
            is_authorized=True,
            is_admin=True,
            authorization_type="email",
            domain="gmail.com",
            message="Access granted (temporary bypass)"
        )
    
    # Standard email check
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not found in user profile"
        )
    
    auth_details = email_auth.get_authorization_summary(user_email)
    
    return AuthorizationCheckResponse(
        email=auth_details["email"],
        is_authorized=auth_details["is_authorized"],
        is_admin=auth_details["is_admin"],
        authorization_type=auth_details["authorization_type"],
        domain=auth_details["domain"] or "",
        message="Access granted" if auth_details["is_authorized"] else "Access denied"
    )


@router.post("/check-email")
async def check_email_authorization(
    request: AuthorizationCheckRequest,
    user: AuthorizedUser
) -> AuthorizationCheckResponse:
    """
    Check if a specific email is authorized (admin only).
    
    Args:
        request: Email to check
        user: Admin user
        
    Returns:
        AuthorizationCheckResponse: Email authorization details
    """
    # Require admin access
    user = require_admin_access(user)
    
    auth_details = email_auth.get_authorization_summary(request.email)
    
    return AuthorizationCheckResponse(
        email=auth_details["email"],
        is_authorized=auth_details["is_authorized"],
        is_admin=auth_details["is_admin"],
        authorization_type=auth_details["authorization_type"],
        domain=auth_details["domain"] or "",
        message="Authorized" if auth_details["is_authorized"] else "Not authorized"
    )


@router.get("/list")
async def list_authorized_users(
    user: AuthorizedUser
) -> EmailListResponse:
    """
    List all authorized emails and domains (admin only).
    
    Args:
        user: Admin user
        
    Returns:
        EmailListResponse: Lists of authorized emails and domains
    """
    # Require admin access
    user = require_admin_access(user)
    
    return EmailListResponse(
        authorized_emails=email_auth.get_authorized_emails(),
        authorized_domains=email_auth.get_authorized_domains()
    )


@router.post("/add-email")
async def add_authorized_email(
    request: AddEmailRequest,
    user: AuthorizedUser
) -> OperationResponse:
    """
    Add an email to the authorized list (admin only).
    
    Args:
        request: Email to add
        user: Admin user
        
    Returns:
        OperationResponse: Operation result
    """
    # Require admin access
    user = require_admin_access(user)
    
    success = email_auth.add_authorized_email(request.email)
    
    if success:
        return OperationResponse(
            success=True,
            message=f"Email '{request.email}' has been authorized successfully"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format or email already exists"
        )


@router.delete("/remove-email")
async def remove_authorized_email(
    request: AddEmailRequest,
    user: AuthorizedUser
) -> OperationResponse:
    """
    Remove an email from the authorized list (admin only).
    
    Args:
        request: Email to remove
        user: Admin user
        
    Returns:
        OperationResponse: Operation result
    """
    # Require admin access
    user = require_admin_access(user)
    
    success = email_auth.remove_authorized_email(request.email)
    
    if success:
        return OperationResponse(
            success=True,
            message=f"Email '{request.email}' has been removed from authorized list"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not found in authorized list"
        )


@router.post("/add-domain")
async def add_authorized_domain(
    request: AddDomainRequest,
    user: AuthorizedUser
) -> OperationResponse:
    """
    Add a domain to the authorized list (admin only).
    
    Args:
        request: Domain to add
        user: Admin user
        
    Returns:
        OperationResponse: Operation result
    """
    # Require admin access
    user = require_admin_access(user)
    
    success = email_auth.add_authorized_domain(request.domain)
    
    if success:
        return OperationResponse(
            success=True,
            message=f"Domain '{request.domain}' has been authorized successfully"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid domain format or domain already exists"
        )


@router.delete("/remove-domain")
async def remove_authorized_domain(
    request: AddDomainRequest,
    user: AuthorizedUser
) -> OperationResponse:
    """
    Remove a domain from the authorized list (admin only).
    
    Args:
        request: Domain to remove
        user: Admin user
        
    Returns:
        OperationResponse: Operation result
    """
    # Require admin access
    user = require_admin_access(user)
    
    success = email_auth.remove_authorized_domain(request.domain)
    
    if success:
        return OperationResponse(
            success=True,
            message=f"Domain '{request.domain}' has been removed from authorized list"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found in authorized list"
        )
