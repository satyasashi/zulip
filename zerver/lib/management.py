# Library code for use in management commands
from argparse import SUPPRESS, ArgumentParser, RawTextHelpFormatter
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.core.management.base import BaseCommand, CommandError, CommandParser

from zerver.models import Client, Realm, UserProfile, get_client


def is_integer_string(val: str) -> bool:
    try:
        int(val)
        return True
    except ValueError:
        return False


def check_config() -> None:
    for (setting_name, default) in settings.REQUIRED_SETTINGS:
        # if required setting is the same as default OR is not found in settings,
        # throw error to add/set that setting in config
        try:
            if settings.__getattr__(setting_name) != default:
                continue
        except AttributeError:
            pass

        raise CommandError(f"Error: You must set {setting_name} in /etc/zulip/settings.py.")


class ZulipBaseCommand(BaseCommand):

    # Fix support for multi-line usage
    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> CommandParser:
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_realm_args(
        self, parser: ArgumentParser, *, required: bool = False, help: Optional[str] = None
    ) -> None:
        if help is None:
            help = """The numeric or string ID (subdomain) of the Zulip organization to modify.
You can use the command list_realms to find ID of the realms in this server."""

        parser.add_argument("-r", "--realm", dest="realm_id", required=required, help=help)

    def add_create_user_args(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "email",
            metavar="<email>",
            nargs="?",
            default=SUPPRESS,
            help="email address of new user",
        )
        parser.add_argument(
            "full_name",
            metavar="<full name>",
            nargs="?",
            default=SUPPRESS,
            help="full name of new user",
        )
        parser.add_argument(
            "--password",
            help="password of new user. For development only."
            "Note that we recommend against setting "
            "passwords this way, since they can be snooped by any user account "
            "on the server via `ps -ef` or by any superuser with"
            "read access to the user's bash history.",
        )
        parser.add_argument(
            "--password-file", help="The file containing the password of the new user."
        )
        parser.add_argument(
            "--this-user-has-accepted-the-tos",
            dest="tos",
            action="store_true",
            help="Acknowledgement that the user has already accepted the ToS.",
        )

    def add_user_list_args(
        self,
        parser: ArgumentParser,
        help: str = "A comma-separated list of email addresses.",
        all_users_help: str = "All users in realm.",
    ) -> None:
        parser.add_argument("-u", "--users", help=help)

        parser.add_argument("-a", "--all-users", action="store_true", help=all_users_help)

    def get_realm(self, options: Dict[str, Any]) -> Optional[Realm]:
        val = options["realm_id"]
        if val is None:
            return None

        # If they specified a realm argument, we need to ensure the
        # realm exists.  We allow two formats: the numeric ID for the
        # realm and the string ID of the realm.
        try:
            if is_integer_string(val):
                return Realm.objects.get(id=val)
            return Realm.objects.get(string_id=val)
        except Realm.DoesNotExist:
            raise CommandError(
                "There is no realm with id '{}'. Aborting.".format(options["realm_id"])
            )

    def get_users(
        self,
        options: Dict[str, Any],
        realm: Optional[Realm],
        is_bot: Optional[bool] = None,
        include_deactivated: bool = False,
    ) -> List[UserProfile]:
        if "all_users" in options:
            all_users = options["all_users"]

            if not options["users"] and not all_users:
                raise CommandError("You have to pass either -u/--users or -a/--all-users.")

            if options["users"] and all_users:
                raise CommandError("You can't use both -u/--users and -a/--all-users.")

            if all_users and realm is None:
                raise CommandError("The --all-users option requires a realm; please pass --realm.")

            if all_users:
                user_profiles = UserProfile.objects.filter(realm=realm)
                if not include_deactivated:
                    user_profiles = user_profiles.filter(is_active=True)
                if is_bot is not None:
                    return user_profiles.filter(is_bot=is_bot)
                return user_profiles

        if options["users"] is None:
            return []
        emails = {email.strip() for email in options["users"].split(",")}
        user_profiles = []
        for email in emails:
            user_profiles.append(self.get_user(email, realm))
        return user_profiles

    def get_user(self, email: str, realm: Optional[Realm]) -> UserProfile:

        # If a realm is specified, try to find the user there, and
        # throw an error if they don't exist.
        if realm is not None:
            try:
                return UserProfile.objects.select_related().get(
                    delivery_email__iexact=email.strip(), realm=realm
                )
            except UserProfile.DoesNotExist:
                raise CommandError(
                    f"The realm '{realm}' does not contain a user with email '{email}'"
                )

        # Realm is None in the remaining code path.  Here, we
        # optimistically try to see if there is exactly one user with
        # that email; if so, we'll return it.
        try:
            return UserProfile.objects.select_related().get(delivery_email__iexact=email.strip())
        except MultipleObjectsReturned:
            raise CommandError(
                "This Zulip server contains multiple users with that email "
                + "(in different realms); please pass `--realm` "
                "to specify which one to modify."
            )
        except UserProfile.DoesNotExist:
            raise CommandError(f"This Zulip server does not contain a user with email '{email}'")

    def get_client(self) -> Client:
        """Returns a Zulip Client object to be used for things done in management commands"""
        return get_client("ZulipServer")
