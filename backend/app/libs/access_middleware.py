"""
Middleware for email-based access control.
Verifies user authorization before allowing access to protected endpoints.
"""

from fastapi import HTTPException, status
from app.auth import AuthorizedUser
from app.libs.email_authorization import email_auth


def verify_email_authorization(user: AuthorizedUser) -> AuthorizedUser:
    """
    Middleware function to verify if a user's email is authorized.
    
    Args:
        user: Authenticated user from Stack Auth
        
    Returns:
        AuthorizedUser: The user if authorized
        
    Raises:
        HTTPException: 403 Forbidden if email is not authorized
    """
    # Get user email from the authenticated user
    user_email = getattr(user, 'email', None)
    user_sub = getattr(user, 'sub', None)
    
    # Debug logging
    print(f"DEBUG: User email: {user_email}")
    print(f"DEBUG: User sub: {user_sub}")
    
    # Temporary fix for Fernando's specific user ID
    if user_sub == "6a7b599d-bd37-4a57-b92f-f95715e8c332":
        print(f"DEBUG: Allowing access for Fernando's user ID: {user_sub}")
        return user
    
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "access_denied",
                "message": "Email address not found in user profile. Please ensure your account has email permissions enabled.",
                "code": "NO_EMAIL",
                "user_id": user_sub,
                "help": "Try logging out and logging back in, making sure to grant email permissions."
            }
        )
    
    # Check if email is authorized
    if not email_auth.is_email_authorized(user_email):
        # Get authorization details for better error message
        auth_details = email_auth.get_authorization_summary(user_email)
        
        print(f"DEBUG: Authorization check failed for {user_email}")
        print(f"DEBUG: Auth details: {auth_details}")
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "access_denied",
                "message": f"Access denied. The email '{user_email}' is not authorized to access TributoFlow.",
                "code": "EMAIL_NOT_AUTHORIZED",
                "email": user_email,
                "domain": auth_details.get("domain"),
                "contact_info": "Contact your administrator to request access."
            }
        )
    
    print(f"DEBUG: Authorization successful for {user_email}")
    # User is authorized, return the user object
    return user


def check_admin_access(user: AuthorizedUser) -> bool:
    """
    Check if user has admin access.
    
    Args:
        user: Authenticated user
        
    Returns:
        bool: True if user is admin
    """
    user_email = getattr(user, 'email', None)
    if not user_email:
        return False
        
    return email_auth.is_admin(user_email)


def require_admin_access(user: AuthorizedUser) -> AuthorizedUser:
    """
    Middleware function to require admin access.
    
    Args:
        user: Authenticated user
        
    Returns:
        AuthorizedUser: The user if admin
        
    Raises:
        HTTPException: 403 Forbidden if not admin
    """
    # First verify email authorization
    user = verify_email_authorization(user)
    
    # Then check admin access
    if not check_admin_access(user):
        user_email = getattr(user, 'email', None)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "admin_access_required",
                "message": "Admin access required for this operation",
                "code": "NOT_ADMIN",
                "email": user_email
            }
        )
    
    return user
