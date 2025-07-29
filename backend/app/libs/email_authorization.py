"""
Library for managing email-based access control.
Controls who can access the TributoFlow dashboard based on authorized email lists.
"""

from typing import Set, List
import re


class EmailAuthorization:
    """
    Manages email-based access control for the TributoFlow dashboard.
    
    Features:
    - Individual email authorization
    - Domain-based authorization
    - Easy management of authorized users
    """
    
    def __init__(self):
        # Individual authorized emails
        self.authorized_emails: Set[str] = {
            "fernando@forvismazars.com",
            "fernando.xavier@forvismazars.com",
        }
        
        # Authorized domains (emails from these domains are automatically allowed)
        self.authorized_domains: Set[str] = {
            "forvismazars.com",
        }
        
        # Admin emails (can manage the system)
        self.admin_emails: Set[str] = {
            "fernando@forvismazars.com",
            "fernando.xavier@forvismazars.com",
        }
    
    def is_email_authorized(self, email: str) -> bool:
        """
        Check if an email is authorized to access the dashboard.
        
        Args:
            email: Email address to check
            
        Returns:
            bool: True if authorized, False otherwise
        """
        if not email or not isinstance(email, str):
            return False
            
        # Normalize email to lowercase
        email = email.lower().strip()
        
        # Validate email format
        if not self._is_valid_email(email):
            return False
        
        # Check if email is directly authorized
        if email in self.authorized_emails:
            return True
            
        # Check if email domain is authorized
        domain = self._extract_domain(email)
        if domain in self.authorized_domains:
            return True
            
        return False
    
    def is_admin(self, email: str) -> bool:
        """
        Check if an email belongs to an admin user.
        
        Args:
            email: Email address to check
            
        Returns:
            bool: True if admin, False otherwise
        """
        if not email:
            return False
            
        email = email.lower().strip()
        return email in self.admin_emails
    
    def add_authorized_email(self, email: str) -> bool:
        """
        Add an email to the authorized list.
        
        Args:
            email: Email address to authorize
            
        Returns:
            bool: True if added successfully, False if invalid
        """
        if not email or not isinstance(email, str):
            return False
            
        email = email.lower().strip()
        
        if not self._is_valid_email(email):
            return False
            
        self.authorized_emails.add(email)
        return True
    
    def remove_authorized_email(self, email: str) -> bool:
        """
        Remove an email from the authorized list.
        
        Args:
            email: Email address to remove
            
        Returns:
            bool: True if removed successfully, False if not found
        """
        if not email:
            return False
            
        email = email.lower().strip()
        
        if email in self.authorized_emails:
            self.authorized_emails.remove(email)
            return True
            
        return False
    
    def add_authorized_domain(self, domain: str) -> bool:
        """
        Add a domain to the authorized list.
        
        Args:
            domain: Domain to authorize (e.g., 'company.com')
            
        Returns:
            bool: True if added successfully, False if invalid
        """
        if not domain or not isinstance(domain, str):
            return False
            
        domain = domain.lower().strip()
        
        # Basic domain validation
        if not self._is_valid_domain(domain):
            return False
            
        self.authorized_domains.add(domain)
        return True
    
    def remove_authorized_domain(self, domain: str) -> bool:
        """
        Remove a domain from the authorized list.
        
        Args:
            domain: Domain to remove
            
        Returns:
            bool: True if removed successfully, False if not found
        """
        if not domain:
            return False
            
        domain = domain.lower().strip()
        
        if domain in self.authorized_domains:
            self.authorized_domains.remove(domain)
            return True
            
        return False
    
    def get_authorized_emails(self) -> List[str]:
        """
        Get list of all authorized emails.
        
        Returns:
            List[str]: List of authorized email addresses
        """
        return sorted(list(self.authorized_emails))
    
    def get_authorized_domains(self) -> List[str]:
        """
        Get list of all authorized domains.
        
        Returns:
            List[str]: List of authorized domains
        """
        return sorted(list(self.authorized_domains))
    
    def get_authorization_summary(self, email: str) -> dict:
        """
        Get detailed authorization information for an email.
        
        Args:
            email: Email address to check
            
        Returns:
            dict: Authorization details
        """
        if not email:
            return {
                "email": None,
                "is_authorized": False,
                "is_admin": False,
                "authorization_type": None,
                "domain": None
            }
            
        email = email.lower().strip()
        domain = self._extract_domain(email)
        
        is_authorized = self.is_email_authorized(email)
        is_admin = self.is_admin(email)
        
        authorization_type = None
        if is_authorized:
            if email in self.authorized_emails:
                authorization_type = "individual_email"
            elif domain in self.authorized_domains:
                authorization_type = "authorized_domain"
        
        return {
            "email": email,
            "is_authorized": is_authorized,
            "is_admin": is_admin,
            "authorization_type": authorization_type,
            "domain": domain
        }
    
    def _is_valid_email(self, email: str) -> bool:
        """
        Validate email format using regex.
        
        Args:
            email: Email address to validate
            
        Returns:
            bool: True if valid email format
        """
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def _is_valid_domain(self, domain: str) -> bool:
        """
        Validate domain format.
        
        Args:
            domain: Domain to validate
            
        Returns:
            bool: True if valid domain format
        """
        pattern = r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, domain))
    
    def _extract_domain(self, email: str) -> str:
        """
        Extract domain from email address.
        
        Args:
            email: Email address
            
        Returns:
            str: Domain part of the email
        """
        if '@' in email:
            return email.split('@')[1]
        return ""


# Global instance for the application
email_auth = EmailAuthorization()
