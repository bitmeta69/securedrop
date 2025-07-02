#
# Copyright (C) 2013-2018 Freedom of the Press Foundation & al
# Copyright (C) 2018 Loic Dachary <loic@dachary.org>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
SecureDrop Admin Toolkit.

For use by administrators to install, maintain, and manage their SD
instances.
"""

import argparse
import base64
import functools
import http.client
import ipaddress
import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar, Union, cast

import prompt_toolkit
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from pkg_resources import parse_version
from prompt_toolkit.document import Document
from prompt_toolkit.validation import ValidationError, Validator

sdlog = logging.getLogger(__name__)

SUPPORT_ONION_URL = "http://sup6h5iyiyenvjkfxbgrjynm5wsgijjoatvnvdgyyi7je3xqm4kh6uqd.onion"
SUPPORT_URL = "https://support.freedom.press"
EXIT_SUCCESS = 0
EXIT_SUBPROCESS_ERROR = 1
EXIT_INTERRUPT = 2

MAX_NAMESERVERS = 3
LIST_SPLIT_RE = re.compile(r"\s*,\s*|\s+")

I18N_CONF_PATH = "/usr/share/securedrop-admin/i18n.json"
I18N_DEFAULT_LOCALES = {"en_US"}

READONLY_CONFIG_PATH = "/usr/share/securedrop-admin"
ANSIBLE_PATH = os.path.join(READONLY_CONFIG_PATH, "ansible-base")
TRANSLATIONS_PATH = os.path.join(READONLY_CONFIG_PATH, "translations")
VERSION_PATH = os.path.join(READONLY_CONFIG_PATH, "version.txt")
CONFIG_PATH = os.path.expanduser("~/.securedrop-admin")
SITE_CONFIG_PATH = os.path.join(CONFIG_PATH, "site-specific")


# Check OpenSSH version - ansible requires an extra argument for scp on OpenSSH 9
def openssh_version() -> int:
    try:
        result = subprocess.run(["ssh", "-V"], capture_output=True, text=True, check=False)
        if result.stderr.startswith("OpenSSH_9"):
            return 9
        elif result.stderr.startswith("OpenSSH_8"):
            return 8
        else:
            return 0
    except subprocess.CalledProcessError:
        return 0
    return 0


def ansible_command() -> List[str]:
    ansible_playbook_path = os.path.join(READONLY_CONFIG_PATH, "venv", "bin", "ansible-playbook")

    cmd = [ansible_playbook_path]
    if openssh_version() == 9:
        cmd = [ansible_playbook_path, "--scp-extra-args='-O'"]
    return cmd


class FingerprintException(Exception):
    pass


class JournalistAlertEmailException(Exception):
    pass


# The type of each entry within SiteConfig.desc
_T = TypeVar("_T", bound=Union[int, str, bool])

# The function type used for the @update_check_required decorator; see
# https://mypy.readthedocs.io/en/stable/generics.html#declaring-decorators
_FuncT = TypeVar("_FuncT", bound=Callable[..., Any])

# Configuration description tuples drive the CLI user experience and the
# validation logic of the  securedrop-admin tool. A tuple is in the following
# format.
#
# (var, default, type, prompt, validator, transform, condition):
#
# var         configuration variable name (will be stored in `site-specific`)
# default     default value (can be a callable)
# type        configuration variable type
# prompt      text prompt presented to the user
# validator   input validator based on `prompt_toolkit`'s Validator class
# transform   transformation function to run on input
# condition   condition under which this prompt is shown, receives the
#             in-progress configuration object as input. Used for "if this
#             then that" branching of prompts.
#
# The mypy type description of the format follows.
_DescEntryType = Tuple[str, _T, Type[_T], str, Optional[Validator], Optional[Callable], Callable]


class SiteConfig:
    class ValidateNotEmpty(Validator):
        def validate(self, document: Document) -> bool:
            if document.text != "":
                return True
            raise ValidationError(message="Must not be an empty string")

    class ValidateTime(Validator):
        def validate(self, document: Document) -> bool:
            if document.text.isdigit() and int(document.text) in range(24):
                return True
            raise ValidationError(message="Must be an integer between 0 and 23")

    class ValidateUser(Validator):
        def validate(self, document: Document) -> bool:
            text = document.text
            if text not in ("", "root", "amnesia"):
                return True
            raise ValidationError(message="Must not be root, amnesia or an empty string")

    class ValidateIP(Validator):
        def validate(self, document: Document) -> bool:
            try:
                ipaddress.ip_address(document.text)
                return True
            except ValueError as e:
                raise ValidationError(message=str(e))

    class ValidateNameservers(Validator):
        def validate(self, document: Document) -> bool:
            candidates = LIST_SPLIT_RE.split(document.text)
            if len(candidates) > MAX_NAMESERVERS:
                raise ValidationError(message="Specify no more than three nameservers.")
            try:
                all(map(ipaddress.ip_address, candidates))
            except ValueError:
                raise ValidationError(
                    message=(
                        "DNS server(s) should be a space/comma-separated list "
                        f"of up to {MAX_NAMESERVERS} IP addresses"
                    )
                )
            return True

    @staticmethod
    def split_list(text: str) -> List[str]:
        """
        Splits a string containing a list of values separated by commas or whitespace.
        """
        return LIST_SPLIT_RE.split(text)

    class ValidatePath(Validator):
        def __init__(self, basedir: str) -> None:
            self.basedir = basedir
            super().__init__()

        def validate(self, document: Document) -> bool:
            if document.text == "":
                raise ValidationError(message="an existing file name is required")
            path = os.path.join(self.basedir, document.text)
            if os.path.exists(path):
                return True
            raise ValidationError(message=path + " file does not exist")

    class ValidateOptionalPath(ValidatePath):
        def validate(self, document: Document) -> bool:
            if document.text == "":
                return True
            return super().validate(document)

    class ValidateYesNo(Validator):
        def validate(self, document: Document) -> bool:
            text = document.text.lower()
            if text in ("yes", "no"):
                return True
            raise ValidationError(message="Must be either yes or no")

    class ValidateFingerprint(Validator):
        def validate(self, document: Document) -> bool:
            text = document.text.replace(" ", "")
            if text == "65A1B5FF195B56353CC63DFFCC40EF1228271441":
                raise ValidationError(message="This is the TEST journalist fingerprint")
            if text == "600BC6D5142C68F35DDBCEA87B597104EDDDC102":
                raise ValidationError(message="This is the TEST admin fingerprint")
            if not re.match("[a-fA-F0-9]{40}$", text):
                raise ValidationError(message="fingerprints must be 40 hexadecimal characters")
            return True

    class ValidateOptionalFingerprint(ValidateFingerprint):
        def validate(self, document: Document) -> bool:
            if document.text == "":
                return True
            return super().validate(document)

    class ValidateInt(Validator):
        def validate(self, document: Document) -> bool:
            if re.match(r"\d+$", document.text):
                return True
            raise ValidationError(message="Must be an integer")

    class Locales:
        def get_translations(self) -> Set[str]:
            translations = I18N_DEFAULT_LOCALES
            for dirname in os.listdir(TRANSLATIONS_PATH):
                if dirname != "messages.pot":
                    translations.add(dirname)
            return translations

    class ValidateLocales(Validator):
        def __init__(self, supported: Set[str]) -> None:
            present = SiteConfig.Locales().get_translations()
            self.available = present & supported

            super().__init__()

        def validate(self, document: Document) -> bool:
            desired = document.text.split()
            missing = set(desired) - self.available
            if not missing:
                return True
            raise ValidationError(
                message="The following locales are not available " + " ".join(missing)
            )

    class ValidateOSSECUsername(Validator):
        def validate(self, document: Document) -> bool:
            text = document.text
            if text and "@" not in text and text != "test":
                return True
            raise ValidationError(message="The SASL username should not include the domain name")

    class ValidateOSSECPassword(Validator):
        def validate(self, document: Document) -> bool:
            text = document.text
            if len(text) >= 8 and text != "password123":
                return True
            raise ValidationError(message="Password for OSSEC email account must be strong")

    class ValidateEmail(Validator):
        def validate(self, document: Document) -> bool:
            text = document.text
            if text == "":
                raise ValidationError(message=("Must not be empty"))
            if "@" not in text:
                raise ValidationError(message=("Must contain a @"))
            return True

    class ValidateOSSECEmail(ValidateEmail):
        def validate(self, document: Document) -> bool:
            super().validate(document)
            text = document.text
            if text != "ossec@ossec.test":
                return True
            raise ValidationError(message=("Must be set to something other than ossec@ossec.test"))

    class ValidateOptionalEmail(ValidateEmail):
        def validate(self, document: Document) -> bool:
            if document.text == "":
                return True
            return super().validate(document)

    def __init__(self) -> None:
        self.config: dict = {}
        # Hold runtime configuration before save, to support
        # referencing other responses during validation
        self._config_in_progress: dict = {}

        supported_locales = I18N_DEFAULT_LOCALES.copy()
        if os.path.exists(I18N_CONF_PATH):
            with open(I18N_CONF_PATH) as i18n_conf_file:
                i18n_conf = json.load(i18n_conf_file)
            supported_locales.update(set(i18n_conf["supported_locales"].keys()))
        locale_validator = SiteConfig.ValidateLocales(supported_locales)

        self.desc: List[_DescEntryType] = [
            (
                "ssh_users",
                "sdadmin",
                str,
                "Username for SSH access to the servers",
                SiteConfig.ValidateUser(),
                None,
                lambda config: True,
            ),
            (
                "daily_reboot_time",
                4,
                int,
                "Daily reboot time of the server (24-hour clock)",
                SiteConfig.ValidateTime(),
                int,
                lambda config: True,
            ),
            (
                "app_ip",
                "10.20.2.2",
                str,
                "Local IPv4 address for the Application Server",
                SiteConfig.ValidateIP(),
                None,
                lambda config: True,
            ),
            (
                "monitor_ip",
                "10.20.3.2",
                str,
                "Local IPv4 address for the Monitor Server",
                SiteConfig.ValidateIP(),
                None,
                lambda config: True,
            ),
            (
                "app_hostname",
                "app",
                str,
                "Hostname for Application Server",
                SiteConfig.ValidateNotEmpty(),
                None,
                lambda config: True,
            ),
            (
                "monitor_hostname",
                "mon",
                str,
                "Hostname for Monitor Server",
                SiteConfig.ValidateNotEmpty(),
                None,
                lambda config: True,
            ),
            (
                "dns_server",
                ["8.8.8.8", "8.8.4.4"],
                list,
                "DNS server(s)",
                SiteConfig.ValidateNameservers(),
                SiteConfig.split_list,
                lambda config: True,
            ),
            (
                "securedrop_app_gpg_public_key",
                "SecureDrop.asc",
                str,
                "Local filepath to public key for " + "SecureDrop Application GPG public key",
                SiteConfig.ValidatePath(CONFIG_PATH),
                None,
                lambda config: True,
            ),
            (
                "securedrop_app_pow_on_source_interface",
                True,
                bool,
                "Enable Tor's proof-of-work defense against denial-of-service attacks for the "
                "Source Interface?",
                SiteConfig.ValidateYesNo(),
                lambda x: x.lower() == "yes",
                lambda config: True,
            ),
            (
                "securedrop_app_https_on_source_interface",
                False,
                bool,
                "Enable HTTPS for the Source Interface (requires EV certificate)?",
                SiteConfig.ValidateYesNo(),
                lambda x: x.lower() == "yes",
                lambda config: True,
            ),
            (
                "securedrop_app_https_certificate_cert_src",
                "",
                str,
                "Local filepath to HTTPS certificate",
                SiteConfig.ValidateOptionalPath(CONFIG_PATH),
                None,
                lambda config: config.get("securedrop_app_https_on_source_interface"),
            ),
            (
                "securedrop_app_https_certificate_key_src",
                "",
                str,
                "Local filepath to HTTPS certificate key",
                SiteConfig.ValidateOptionalPath(CONFIG_PATH),
                None,
                lambda config: config.get("securedrop_app_https_on_source_interface"),
            ),
            (
                "securedrop_app_https_certificate_chain_src",
                "",
                str,
                "Local filepath to HTTPS certificate chain file",
                SiteConfig.ValidateOptionalPath(CONFIG_PATH),
                None,
                lambda config: config.get("securedrop_app_https_on_source_interface"),
            ),
            (
                "securedrop_app_gpg_fingerprint",
                "",
                str,
                "Full fingerprint for the SecureDrop Application GPG Key",
                SiteConfig.ValidateFingerprint(),
                self.sanitize_fingerprint,
                lambda config: True,
            ),
            (
                "ossec_alert_gpg_public_key",
                "ossec.pub",
                str,
                "Local filepath to OSSEC alerts GPG public key",
                SiteConfig.ValidatePath(CONFIG_PATH),
                None,
                lambda config: True,
            ),
            (
                "ossec_gpg_fpr",
                "",
                str,
                "Full fingerprint for the OSSEC alerts GPG public key",
                SiteConfig.ValidateFingerprint(),
                self.sanitize_fingerprint,
                lambda config: True,
            ),
            (
                "ossec_alert_email",
                "",
                str,
                "Admin email address for receiving OSSEC alerts",
                SiteConfig.ValidateOSSECEmail(),
                None,
                lambda config: True,
            ),
            (
                "journalist_alert_gpg_public_key",
                "",
                str,
                "Local filepath to journalist alerts GPG public key (optional)",
                SiteConfig.ValidateOptionalPath(CONFIG_PATH),
                None,
                lambda config: True,
            ),
            (
                "journalist_gpg_fpr",
                "",
                str,
                "Full fingerprint for the journalist alerts " + "GPG public key (optional)",
                SiteConfig.ValidateOptionalFingerprint(),
                self.sanitize_fingerprint,
                lambda config: config.get("journalist_alert_gpg_public_key"),
            ),
            (
                "journalist_alert_email",
                "",
                str,
                "Email address for receiving journalist alerts (optional)",
                SiteConfig.ValidateOptionalEmail(),
                None,
                lambda config: config.get("journalist_alert_gpg_public_key"),
            ),
            (
                "smtp_relay",
                "smtp.gmail.com",
                str,
                "SMTP relay for sending OSSEC alerts",
                SiteConfig.ValidateNotEmpty(),
                None,
                lambda config: True,
            ),
            (
                "smtp_relay_port",
                587,
                int,
                "SMTP port for sending OSSEC alerts",
                SiteConfig.ValidateInt(),
                int,
                lambda config: True,
            ),
            (
                "sasl_domain",
                "gmail.com",
                str,
                "SASL domain for sending OSSEC alerts",
                None,
                None,
                lambda config: True,
            ),
            (
                "sasl_username",
                "",
                str,
                "SASL username for sending OSSEC alerts",
                SiteConfig.ValidateOSSECUsername(),
                None,
                lambda config: True,
            ),
            (
                "sasl_password",
                "",
                str,
                "SASL password for sending OSSEC alerts",
                SiteConfig.ValidateOSSECPassword(),
                None,
                lambda config: True,
            ),
            (
                "enable_ssh_over_tor",
                True,
                bool,
                "Enable SSH over Tor (recommended, disables SSH over LAN). "
                + "If you respond no, SSH will be available over LAN only",
                SiteConfig.ValidateYesNo(),
                lambda x: x.lower() == "yes",
                lambda config: True,
            ),
            (
                "securedrop_supported_locales",
                [],
                list,
                "Space separated list of additional locales to support "
                "(" + " ".join(sorted(list(locale_validator.available))) + ")",
                locale_validator,
                str.split,
                lambda config: True,
            ),
        ]

    def load_and_update_config(self, validate: bool = True, prompt: bool = True) -> bool:
        if self.exists():
            self.config = self.load(validate)
        elif not prompt:
            sdlog.error('Please run "securedrop-admin sdconfig" first.')
            sys.exit(1)

        return self.update_config(prompt)

    def update_config(self, prompt: bool = True) -> bool:
        if prompt:
            self.config.update(self.user_prompt_config())

        # Always add the config path to the config, so ansible can reference it
        self.config["config_path"] = CONFIG_PATH

        self.save()
        self.validate_gpg_keys()
        self.validate_journalist_alert_email()
        return True

    def user_prompt_config(self) -> Dict[str, Any]:
        self._config_in_progress = {}
        for desc in self.desc:
            (var, default, type, prompt, validator, transform, condition) = desc
            if not condition(self._config_in_progress):
                self._config_in_progress[var] = ""
                continue
            self._config_in_progress[var] = self.user_prompt_config_one(desc, self.config.get(var))
        return self._config_in_progress

    def user_prompt_config_one(self, desc: _DescEntryType, from_config: Optional[Any]) -> Any:
        (var, default, type, prompt, validator, transform, condition) = desc
        if from_config is not None:
            default = from_config
        prompt += ": "

        # The following is for the dynamic check of the user input
        # for the previous question, as we are calling the default value
        # function dynamically, we can get the right value based on the
        # previous user input.
        if callable(default):
            default = default()
        return self.validated_input(prompt, default, validator, transform)

    def validated_input(
        self, prompt: str, default: Any, validator: Validator, transform: Optional[Callable]
    ) -> Any:
        if type(default) is bool:
            default = "yes" if default else "no"
        if type(default) is int:
            default = str(default)
        if isinstance(default, list):
            default = " ".join(default)
        if type(default) is not str:
            default = str(default)
        value = prompt_toolkit.prompt(prompt, default=default, validator=validator)
        if transform:
            return transform(value)
        else:
            return value

    def sanitize_fingerprint(self, value: str) -> str:
        return value.upper().replace(" ", "").strip()

    def validate_gpg_keys(self) -> bool:
        keys = (
            ("securedrop_app_gpg_public_key", "securedrop_app_gpg_fingerprint"),
            ("ossec_alert_gpg_public_key", "ossec_gpg_fpr"),
            ("journalist_alert_gpg_public_key", "journalist_gpg_fpr"),
        )
        for public_key, fingerprint in keys:
            if self.config[public_key] == "" and self.config[fingerprint] == "":
                continue
            public_key = os.path.join(CONFIG_PATH, self.config[public_key])
            fingerprint = self.config[fingerprint]
            try:
                sdlog.debug(
                    subprocess.check_output(
                        ["/usr/bin/validate-gpg-key.sh", public_key, fingerprint],
                        stderr=subprocess.STDOUT,
                    )
                )
            except subprocess.CalledProcessError as e:
                sdlog.debug(e.output)
                message = f"{fingerprint}: Fingerprint validation failed"

                # The validation script returns different error codes depending on what
                # the cause of the validation failure was. See `admin/bin/validate-gpg-key.sh`
                if e.returncode == 1:
                    message = (
                        f"fingerprint {fingerprint} does not match "
                        + f"the public key {public_key}"
                    )
                elif e.returncode == 2:
                    message = (
                        f"fingerprint {fingerprint} "
                        + "failed sq-keyring-linter check. You may be using an older key that "
                        + "needs to be updated. Please contact your SecureDrop administrator, or "
                        + "https://support.freedom.press for assistance."
                    )
                raise FingerprintException(message)
        return True

    def validate_journalist_alert_email(self) -> bool:
        if (
            self.config["journalist_alert_gpg_public_key"] == ""
            and self.config["journalist_gpg_fpr"] == ""
        ):
            return True

        class Document:
            def __init__(self, text: str) -> None:
                self.text = text

        try:
            SiteConfig.ValidateEmail().validate(Document(self.config["journalist_alert_email"]))
        except ValidationError as e:
            raise JournalistAlertEmailException("journalist alerts email: " + e.message)
        return True

    def exists(self) -> bool:
        return os.path.exists(SITE_CONFIG_PATH)

    def save(self) -> None:
        with open(SITE_CONFIG_PATH, "w") as site_config_file:
            yaml.safe_dump(self.config, site_config_file, default_flow_style=False)

    def clean_config(self, config: Dict) -> Dict:
        """
        Cleans a loaded config without prompting.

        For every variable defined in self.desc, validate its value in
        the supplied configuration dictionary, run the value through
        its defined transformer, and add the result to a clean version
        of the configuration.

        If no configuration variable triggers a ValidationError, the
        clean configuration will be returned.
        """
        clean_config = {}
        clean_config.update(config)
        for desc in self.desc:
            var, default, vartype, prompt, validator, transform, condition = desc
            if var in clean_config:
                value = clean_config[var]
                if isinstance(value, list):
                    text = " ".join(str(v) for v in value)
                elif isinstance(value, bool):
                    text = "yes" if value else "no"
                else:
                    text = str(value)

                if validator is not None:
                    try:
                        validator.validate(Document(text))
                    except ValidationError as e:
                        sdlog.error(e)
                        sdlog.error(
                            "Error loading configuration. "
                            'Please run "securedrop-admin sdconfig" again.'
                        )
                        raise
                clean_config[var] = transform(text) if transform else text
                if var not in self._config_in_progress:
                    self._config_in_progress[var] = clean_config[var]
        return clean_config

    def load(self, validate: bool = True) -> Dict:
        """
        Loads the site configuration file.

        If validate is True, then each configuration variable that has
        an entry in self.desc is validated and transformed according
        to current specifications.
        """
        try:
            with open(SITE_CONFIG_PATH) as site_config_file:
                c = yaml.safe_load(site_config_file)
                return self.clean_config(c) if validate else c
        except OSError:
            sdlog.error("Config file missing, re-run with sdconfig")
            raise
        except yaml.YAMLError:
            sdlog.error(f"There was an issue processing {SITE_CONFIG_PATH}")
            raise


def setup_logger(verbose: bool = False) -> None:
    """Configure logging handler"""
    # Set default level on parent
    sdlog.setLevel(logging.DEBUG)
    level = logging.DEBUG if verbose else logging.INFO

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    stdout.setLevel(level)
    sdlog.addHandler(stdout)


def update_check_required(cmd_name: str) -> Callable[[_FuncT], _FuncT]:
    """
    This decorator can be added to any subcommand that is part of securedrop-admin
    via `@update_check_required("name_of_subcommand")`. It forces a check for
    updates, and aborts if the locally installed code is out of date. It should
    be generally added to all subcommands that make modifications on the
    server or on the Admin Workstation.

    The user can override this check by specifying the --force argument before
    any subcommand.
    """

    def decorator_update_check(func: _FuncT) -> _FuncT:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cli_args = args[0]
            if cli_args.force:
                sdlog.info("Skipping update check because --force argument was provided.")
                return func(*args, **kwargs)

            update_status, latest_tag = check_for_updates(cli_args)
            if update_status is True:
                sdlog.error(
                    "You are not running the most recent signed SecureDrop release "
                    "on this workstation."
                )
                sdlog.error(f"Latest available version: {latest_tag}")

                sdlog.error(
                    "If you are certain you want to proceed, run:\n\n\t"
                    f"./securedrop-admin --force {cmd_name}\n"
                )
                sdlog.error("To apply the latest updates, install operating system updates.\n")
                sdlog.error(
                    "If this fails, see the latest upgrade guide on "
                    "https://docs.securedrop.org/ for instructions."
                )
                sys.exit(1)
            return func(*args, **kwargs)

        return cast(_FuncT, wrapper)

    return decorator_update_check


@update_check_required("sdconfig")
def sdconfig(args: argparse.Namespace) -> int:
    """Configure SD site settings"""
    SiteConfig().load_and_update_config(validate=False)
    return 0


def generate_new_v3_keys() -> Tuple[str, str]:
    """This function generate new keys for Tor v3 onion
    services and returns them as as tuple.

    :returns: Tuple(public_key, private_key)
    """

    private_key = x25519.X25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    # Base32 encode and remove base32 padding characters (`=`)
    public = base64.b32encode(public_bytes).replace(b"=", b"").decode("utf-8")
    private = base64.b32encode(private_bytes).replace(b"=", b"").decode("utf-8")
    return public, private


def find_or_generate_new_torv3_keys(args: argparse.Namespace) -> int:
    """
    This method will either read v3 Tor onion service keys if found or generate
    a new public/private keypair.
    """
    secret_key_path = os.path.join(CONFIG_PATH, "tor_v3_keys.json")
    if os.path.exists(secret_key_path):
        print(f"Tor v3 onion service keys already exist in: {secret_key_path}")
        return 0
    # No old keys, generate and store them first
    app_journalist_public_key, app_journalist_private_key = generate_new_v3_keys()
    # For app SSH service
    app_ssh_public_key, app_ssh_private_key = generate_new_v3_keys()
    # For mon SSH service
    mon_ssh_public_key, mon_ssh_private_key = generate_new_v3_keys()
    tor_v3_service_info = {
        "app_journalist_public_key": app_journalist_public_key,
        "app_journalist_private_key": app_journalist_private_key,
        "app_ssh_public_key": app_ssh_public_key,
        "app_ssh_private_key": app_ssh_private_key,
        "mon_ssh_public_key": mon_ssh_public_key,
        "mon_ssh_private_key": mon_ssh_private_key,
    }
    with open(secret_key_path, "w") as fobj:
        json.dump(tor_v3_service_info, fobj, indent=4)
    print(f"Tor v3 onion service keys generated and stored in: {secret_key_path}")
    return 0


@update_check_required("install")
def install_securedrop(args: argparse.Namespace) -> int:
    """Install/Update SecureDrop"""

    SiteConfig().load_and_update_config(prompt=False)

    sdlog.info("Now installing SecureDrop on remote servers.")
    sdlog.info("You will be prompted for the sudo password on the servers.")
    sdlog.info("The sudo password is only necessary during initial installation.")
    return subprocess.check_call(
        ansible_command()
        + [
            os.path.join(ANSIBLE_PATH, "securedrop-prod.yml"),
            "--ask-become-pass",
            "--extra-vars",
            f"@{SITE_CONFIG_PATH}",
        ],
        cwd=ANSIBLE_PATH,
    )


def verify_install(args: argparse.Namespace) -> int:
    """Run configuration tests against SecureDrop servers"""

    sdlog.info("Running configuration tests: ")
    testinfra_cmd = ["./devops/scripts/run_prod_testinfra"]
    return subprocess.check_call(testinfra_cmd, cwd=os.getcwd())


@update_check_required("backup")
def backup_securedrop(args: argparse.Namespace) -> int:
    """Perform backup of the SecureDrop Application Server.
    Creates a tarball of submissions and server config, and fetches
    back to the Admin Workstation. Future `restore` actions can be performed
    with the backup tarball."""
    sdlog.info("Backing up the Sec Application Server")
    ansible_cmd = ansible_command() + [
        os.path.join(ANSIBLE_PATH, "securedrop-backup.yml"),
        "--extra-vars",
        f"@{SITE_CONFIG_PATH}",
    ]
    return subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)


@update_check_required("restore")
def restore_securedrop(args: argparse.Namespace) -> int:
    """Perform restore of the SecureDrop Application Server.
    Requires a tarball of submissions and server config, created via
    the `backup` action."""
    sdlog.info("Restoring the SecureDrop Application Server from backup")
    # Canonicalize filepath to backup tarball, so Ansible sees only the
    # basename. The files must live in args.ansible_path,
    # but the securedrop-admin
    # script will be invoked from the repo root, so preceding dirs are likely.
    restore_file_basename = os.path.basename(args.restore_file)

    # Would like readable output if there's a problem
    os.environ["ANSIBLE_STDOUT_CALLBACK"] = "debug"

    ansible_cmd = ansible_command() + [
        os.path.join(ANSIBLE_PATH, "securedrop-restore.yml"),
        "--extra-vars",
        f"@{SITE_CONFIG_PATH}",
        "-e",
    ]

    ansible_cmd_extras = [
        f"restore_file='{restore_file_basename}'",
    ]

    if args.restore_skip_tor:
        ansible_cmd_extras.append("restore_skip_tor='True'")

    if args.restore_manual_transfer:
        ansible_cmd_extras.append("restore_manual_transfer='True'")

    ansible_cmd.append(" ".join(ansible_cmd_extras))
    return subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)


@update_check_required("localconfig")
def run_local_config(args: argparse.Namespace) -> int:
    """Configure either Tails or Qubes environment post SD install"""
    sdlog.info("Configuring local environment")

    with open("/etc/os-release") as os_release_file:
        os_release = os_release_file.read()

    if 'NAME="Debian GNU/Linux"' in os_release:
        sdlog.info("Detected Debian, running Qubes configuration")
        ansible_cmd = ansible_command() + [
            os.path.join(ANSIBLE_PATH, "securedrop-qubes.yml"),
            "--extra-vars",
            f"@{SITE_CONFIG_PATH}",
            # Passing an empty inventory file to override the automatic dynamic
            # inventory script, which fails if no site vars are configured.
            "-i",
            "/dev/null",
        ]
        return subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)
    elif 'NAME="Tails"' in os_release:
        sdlog.info("Detected Tails, running Tails configuration")
        sdlog.info(
            "You'll be prompted for the temporary Tails admin password,"
            " which was set on Tails login screen"
        )
        ansible_cmd = ansible_command() + [
            os.path.join(ANSIBLE_PATH, "securedrop-tails.yml"),
            "--ask-become-pass",
            "--extra-vars",
            f"@{SITE_CONFIG_PATH}",
            # Passing an empty inventory file to override the automatic dynamic
            # inventory script, which fails if no site vars are configured.
            "-i",
            "/dev/null",
        ]
        return subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)

    sdlog.error("Unsupported OS detected. Please run the appropriate configuration script.")
    return 1


def check_for_updates_wrapper(args: argparse.Namespace) -> int:
    check_for_updates(args)
    # Because the command worked properly exit with 0.
    return 0


def check_for_updates(args: argparse.Namespace) -> Tuple[bool, str]:
    """Check for SecureDrop updates"""
    sdlog.info("Checking for SecureDrop updates...")

    # Load the current SecureDrop version
    with open(VERSION_PATH) as f:
        current_version = f.read().strip()

    # Use the GitHub API to determine the latest release
    # Using http.client instead of requests to avoid adding a dependency
    try:
        conn = http.client.HTTPSConnection("api.github.com", timeout=10)
        headers = {
            "User-Agent": "securedrop-admin",
            "Accept": "application/vnd.github.v3+json",
        }
        conn.request("GET", "/repos/freedomofpress/securedrop/releases/latest", headers=headers)
        response = conn.getresponse()
        if response.status != 200:
            raise Exception(f"GitHub API returned status {response.status}")
        data = response.read().decode("utf-8")
        latest_release = json.loads(data)
        conn.close()
    except Exception as e:
        sdlog.error(f"Failed to check for updates: {e}")
        return False, current_version

    latest_version = latest_release.get("tag_name", "")

    if current_version != latest_version:
        sdlog.info(f"Current version: {current_version}")
        sdlog.info(f"Latest version: {latest_version}")
        sdlog.info("Update needed")
        return True, latest_version
    sdlog.info("All updates applied")
    return False, latest_version


@update_check_required("logs")
def get_logs(args: argparse.Namespace) -> int:
    """Get logs for forensics and debugging purposes"""
    sdlog.info("Gathering logs for forensics and debugging")
    ansible_cmd = ansible_command() + [
        os.path.join(ANSIBLE_PATH, "securedrop-logs.yml"),
        "--extra-vars",
        f"@{SITE_CONFIG_PATH}",
    ]

    subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)
    sdlog.info(
        "Please send the encrypted logs to securedrop@freedom.press or "
        "upload them to the SecureDrop support portal: " + SUPPORT_URL
    )
    return 0


@update_check_required("noble_migration")
def noble_migration(args: argparse.Namespace) -> int:
    """Upgrade to Ubuntu Noble"""
    sdlog.info("Beginning the upgrade to Ubuntu Noble")
    ansible_cmd = ansible_command() + [
        os.path.join(ANSIBLE_PATH, "securedrop-noble-migration.yml"),
        "--extra-vars",
        f"@{SITE_CONFIG_PATH}",
    ]

    subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)
    sdlog.info("Upgrade to Ubuntu Noble complete!")
    return 0


@update_check_required("reset_admin_access")
def reset_admin_access(args: argparse.Namespace) -> int:
    """Resets SSH access to the SecureDrop servers, locking it to
    this Admin Workstation."""
    sdlog.info("Resetting SSH access to the SecureDrop servers")
    ansible_cmd = ansible_command() + [
        os.path.join(ANSIBLE_PATH, "securedrop-reset-ssh-key.yml"),
        "--extra-vars",
        f"@{SITE_CONFIG_PATH}",
    ]
    return subprocess.check_call(ansible_cmd, cwd=ANSIBLE_PATH)


def parse_argv(argv: List[str]) -> argparse.Namespace:
    class ArgParseFormatterCombo(
        argparse.ArgumentDefaultsHelpFormatter, argparse.RawTextHelpFormatter
    ):
        """Needed to combine formatting classes for help output"""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=ArgParseFormatterCombo)
    parser.add_argument(
        "-v", action="store_true", default=False, help="Increase verbosity on output"
    )
    parser.add_argument(
        "-d",
        action="store_true",
        default=False,
        help="Developer mode. Not to be used in production.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        required=False,
        help="force command execution without update check",
    )
    subparsers = parser.add_subparsers()

    parse_sdconfig = subparsers.add_parser("sdconfig", help=sdconfig.__doc__)
    parse_sdconfig.set_defaults(func=sdconfig)

    parse_install = subparsers.add_parser("install", help=install_securedrop.__doc__)
    parse_install.set_defaults(func=install_securedrop)

    parse_localconfig = subparsers.add_parser(
        "localconfig", aliases=["tailsconfig", "qubesconfig"], help=run_local_config.__doc__
    )
    parse_localconfig.set_defaults(func=run_local_config)

    parse_generate_tor_keys = subparsers.add_parser(
        "generate_v3_keys", help=find_or_generate_new_torv3_keys.__doc__
    )
    parse_generate_tor_keys.set_defaults(func=find_or_generate_new_torv3_keys)

    parse_backup = subparsers.add_parser("backup", help=backup_securedrop.__doc__)
    parse_backup.set_defaults(func=backup_securedrop)

    parse_restore = subparsers.add_parser("restore", help=restore_securedrop.__doc__)
    parse_restore.set_defaults(func=restore_securedrop)
    parse_restore.add_argument("restore_file")
    parse_restore.add_argument(
        "--preserve-tor-config",
        default=False,
        action="store_true",
        dest="restore_skip_tor",
        help="Preserve the server's current Tor config",
    )

    parse_restore.add_argument(
        "--no-transfer",
        default=False,
        action="store_true",
        dest="restore_manual_transfer",
        help="Restore using a backup file already present on the server",
    )

    parse_check_updates = subparsers.add_parser("check_for_updates", help=check_for_updates.__doc__)
    parse_check_updates.set_defaults(func=check_for_updates_wrapper)

    parse_logs = subparsers.add_parser("logs", help=get_logs.__doc__)
    parse_logs.set_defaults(func=get_logs)

    parse_noble_migration = subparsers.add_parser("noble_migration", help=noble_migration.__doc__)
    parse_noble_migration.set_defaults(func=noble_migration)

    parse_reset_ssh = subparsers.add_parser("reset_admin_access", help=reset_admin_access.__doc__)
    parse_reset_ssh.set_defaults(func=reset_admin_access)

    parse_verify = subparsers.add_parser("verify", help=verify_install.__doc__)
    parse_verify.set_defaults(func=verify_install)

    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        print("Please specify an operation.\n")
        parser.print_help()
        sys.exit(1)

    return args


def main(argv: List[str]) -> None:
    args = parse_argv(argv)
    setup_logger(args.v)
    if args.v:
        return_code = args.func(args)
        if return_code != 0:
            sys.exit(EXIT_SUBPROCESS_ERROR)
    else:
        try:
            return_code = args.func(args)
        except KeyboardInterrupt:
            print("Process was interrupted.")
            sys.exit(EXIT_INTERRUPT)
        except subprocess.CalledProcessError as e:
            print(f"ERROR (run with -v for more): {e}", file=sys.stderr)
            sys.exit(EXIT_SUBPROCESS_ERROR)
        except Exception as e:
            raise SystemExit(f"ERROR (run with -v for more): {e}")
    if return_code == 0:
        sys.exit(EXIT_SUCCESS)
    else:
        sys.exit(EXIT_SUBPROCESS_ERROR)


if __name__ == "__main__":
    main(sys.argv[1:])
