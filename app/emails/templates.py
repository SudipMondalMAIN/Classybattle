"""
HTML email templates for transactional emails.
"""


def _base_template(title: str, full_name: str, body_html: str) -> str:
    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #0d0d0d; padding: 24px;">
        <div style="max-width: 480px; margin: 0 auto; background: #1a1a1a; border-radius: 12px; padding: 32px; color: #f5f5f5;">
          <h2 style="color: #ffcc00; margin-top: 0;">{title}</h2>
          <p>Hi {full_name},</p>
          {body_html}
          <p style="margin-top: 32px; font-size: 12px; color: #888;">
            If you did not request this, please ignore this email.
          </p>
          <p style="font-size: 12px; color: #888;">— The ClassyBattle Team</p>
        </div>
      </body>
    </html>
    """


def otp_email_template(full_name: str, otp: str, expiry_minutes: int) -> str:
    body = f"""
      <p>Use the code below to verify your ClassyBattle account:</p>
      <div style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #ffcc00; text-align: center; margin: 24px 0;">
        {otp}
      </div>
      <p>This code expires in {expiry_minutes} minutes.</p>
    """
    return _base_template("Verify Your Account", full_name, body)


def password_reset_otp_template(full_name: str, otp: str, expiry_minutes: int) -> str:
    body = f"""
      <p>Use the code below to reset your ClassyBattle password:</p>
      <div style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #ffcc00; text-align: center; margin: 24px 0;">
        {otp}
      </div>
      <p>This code expires in {expiry_minutes} minutes.</p>
    """
    return _base_template("Reset Your Password", full_name, body)
