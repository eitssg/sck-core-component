import core_helper.aws as aws


def assume_role(role: str) -> dict | None:
    """
    Assume Roles in AWS.  Returns the credientials of the assumed role or the current session.

    If credientials are not determinable, this function returns None.
    """

    result = aws.assume_role(role=role)

    return result
