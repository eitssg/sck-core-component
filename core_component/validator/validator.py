import re
from typing import Any
import core_logging as log
import json
import traceback


class Validator:
    AWS_STRING_FUNCTIONS = [
        "Fn::Base64",
        "Fn::FindInMap",
        "Fn::GetAtt",
        "Fn::ImportValue",
        "Fn::Join",
        "Fn::Select",
        "Fn::Sub",
        "Ref",
    ]

    spec: dict
    definition_name: str
    definition: dict
    validation_errors: list[dict]
    validation_warnings: list[dict]
    meta_prefix: str

    def __init__(self, definition_name: str, definition: dict, spec: dict, meta_prefix: str = "_"):
        self.spec = spec
        self.definition_name = definition_name
        self.definition = definition
        self.validation_errors = []
        self.validation_warnings = []
        self.meta_prefix = meta_prefix

    def validate(self) -> tuple[list[dict], list[dict]]:
        log.info("Validating component '{}'".format(self.definition_name))

        # Empty validation errors at the start of every run
        self.clean_validation_results()

        try:
            self.__validate("", self.spec, self.definition_name, self.definition)
        except Exception as e:
            log.error(
                "Internal error during validation - {}".format(e),
                details={"StackTrace": traceback.format_exc()},
            )
            self.__log_validation_error(
                "",
                self.spec,
                self.definition_name,
                self.definition,
                "Internal error during validation - {}".format(e),
            )

        return self.get_validation_results()

    def get_validation_results(self) -> tuple[list[dict], list[dict]]:
        return sorted(self.validation_errors, key=lambda x: x["Details"]["Key"]), sorted(
            self.validation_warnings, key=lambda x: x["Details"]["Key"]
        )

    def clean_validation_results(self):
        self.validation_errors = []
        self.validation_warnings = []

    def __spec_key(self, key):
        return self.meta_prefix + key

    def __log_validation_error(self, spec_key: str, spec: dict, obj_key: str, obj: Any, message: str):
        item: dict = {
            "Component": self.definition_name,
            "Details": {"Key": obj_key},
            "Message": "Validation error - {}".format(message),
        }

        if self.__spec_key("Documentation") in spec:
            item["Details"]["Documentation"] = spec[self.__spec_key("Documentation")]

        self.validation_errors.append(item)

    def __log_validation_warning(self, spec_key: str, spec: dict, obj_key: str, obj: dict, message: str):
        item: dict = {
            "Component": self.definition_name,
            "Details": {"Key": obj_key},
            "Message": "Validation warning - {}".format(message),
        }

        if self.__spec_key("Documentation") in spec:
            item["Details"]["Documentation"] = spec[self.__spec_key("Documentation")]

        self.validation_warnings.append(item)

    def __validate(self, spec_key: str, spec: dict, obj_key: str, obj: Any):  # noqa: C901
        # Current key is last label of the FQ key
        key = obj_key.split(".")[-1]

        # Key enumeration
        if self.__spec_key("KeyEnum") in spec:
            # Validate Enum constraint
            enum_values = self.__eval(spec_key, spec[self.__spec_key("KeyEnum")], obj_key, key)
            if key not in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    key,
                    "Key must be one of {}, received '{}'".format(enum_values, key),
                )

        # Key not-in enumeration
        if self.__spec_key("KeyNotEnum") in spec:
            not_enum_values = self.__eval(spec_key, spec[self.__spec_key("KeyNotEnum")], obj_key, key)
            if key in not_enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    key,
                    "Key must NOT be one of {}, received '{}'".format(enum_values, key),
                )

        # Key regex match
        if self.__spec_key("KeyRegex") in spec:
            # Validate Regex constraint
            key_regex = self.__eval(spec_key, spec[self.__spec_key("KeyRegex")], obj_key, key)
            if not re.match("^({})$".format(key_regex), key):
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    key,
                    "Key must match regex '{}', received '{}'".format(key_regex, key),
                )

        # Key length
        min_length, max_length = self.__parse_key_length(spec_key, spec, obj_key, obj)
        if min_length == max_length and (len(key) < min_length or len(key) > max_length):
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Key must be {} characters long, received '{}' ({}) characters".format(min_length, key, len(key)),
            )
        elif len(key) < min_length:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Key must be at least {} characters long, received '{}' ({}) characters".format(min_length, key, len(key)),
            )
        elif len(key) > max_length:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Key must be at most {} characters long, received '{}' ({}) characters".format(max_length, key, len(key)),
            )

        # Validation warnings
        if self.__spec_key("Warning") in spec:
            self.__log_validation_warning(spec_key, spec, obj_key, obj, spec[self.__spec_key("Warning")])

        # Validate based on type
        spec_type = spec.get(self.__spec_key("Type"), "dict")
        if spec_type == "aws-string":
            self.__validate_aws_string(spec_key, spec, obj_key, obj)
        elif spec_type == "boolean":
            self.__validate_boolean(spec_key, spec, obj_key, obj)
        elif spec_type == "dict":
            self.__validate_dict(spec_key, spec, obj_key, obj)
        elif spec_type == "eval-boolean":
            self.__validate_eval_boolean(spec_key, spec, obj_key, obj)
        elif spec_type == "float":
            self.__validate_float(spec_key, spec, obj_key, obj)
        elif spec_type == "freeform":
            self.__validate_freeform(spec_key, spec, obj_key, obj)
        elif spec_type == "int":
            self.__validate_int(spec_key, spec, obj_key, obj)
        elif spec_type == "json-string":
            self.__validate_json_string(spec_key, spec, obj_key, obj)
        elif spec_type == "list":
            self.__validate_list(spec_key, spec, obj_key, obj)
        elif spec_type == "multiple":
            self.__validate_multiple(spec_key, spec, obj_key, obj)
        elif spec_type == "scalar":
            self.__validate_scalar(spec_key, spec, obj_key, obj)
        elif spec_type == "string":
            self.__validate_string(spec_key, spec, obj_key, obj)
        else:
            log.error("Unknown type '{}' for spec '{}', failed to validate obj '{}'".format(spec_type, spec_key, obj_key))

    def __parse_cardinality(self, spec_key: str, cardinality: str, obj_key: str, obj: Any) -> tuple[int, int]:
        cardinality = self.__eval(spec_key, cardinality, obj_key, obj)
        match = re.match(r"^(?:([0-9]+)|(?:([0-9]+)-([0-9]+))|(?:([0-9]+)\+))$", str(cardinality))
        if not match:
            raise Exception("Invalid cardinality '{}' on spec '{}'".format(cardinality, spec_key))

        matches = match.groups()
        if matches[0]:
            # Exact number (eg: 1)
            min = int(matches[0])
            max = min
        elif matches[1]:
            # Closed range (eg: 1-6)
            min = int(matches[1])
            max = int(matches[2])
        elif matches[3]:
            # Open ended range (eg: 1+)
            min = int(matches[3])
            max = 10000
        else:
            raise Exception("Invalid cardinality '{}' on spec '{}'".format(cardinality, spec_key))

        # Correct the bounds so max is >= min
        if max < min:
            raise Exception("Invalid min and max bounds on cardinality '{}'".format(cardinality))

        return min, max

    def __parse_dict_cardinality(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> tuple[int, int]:
        if self.__spec_key("KeyCardinality") in spec:
            # Cardinality is specified - use it for both the min and max values
            return self.__parse_cardinality(spec_key, spec[self.__spec_key("KeyCardinality")], obj_key, obj)

        required = self.__eval(spec_key, spec.get(self.__spec_key("Required"), True), obj_key, obj)
        configurable = self.__eval(spec_key, spec.get(self.__spec_key("Configurable"), True), obj_key, obj)

        if not configurable:
            # Not configurable - min 0, max 0
            return 0, 0

        if required:
            # Required - min 1, max 1
            return 1, 1

        # Configurable but not required - min 0, max 1
        return 0, 1

    def __parse_key_length(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> tuple[int, int]:
        if self.__spec_key("KeyLength") in spec:
            return self.__parse_cardinality(spec_key, spec[self.__spec_key("KeyLength")], obj_key, obj)
        else:
            return 0, 100000

    def __parse_list_length(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> tuple[int, int]:
        if self.__spec_key("ListLength") in spec:
            return self.__parse_cardinality(spec_key, spec[self.__spec_key("ListLength")], obj_key, obj)
        else:
            return 0, 100000

    def __parse_string_length(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> tuple[int, int]:
        if self.__spec_key("StringLength") in spec:
            return self.__parse_cardinality(spec_key, spec[self.__spec_key("StringLength")], obj_key, obj)
        else:
            return 0, 100000

    def __is_aws_string(self, spec: dict, obj: dict) -> bool:
        return isinstance(obj, str) or (isinstance(obj, dict) and len(obj) == 1 and next(iter(obj)) in self.AWS_STRING_FUNCTIONS)

    def __validate_aws_string(self, spec_key: str, spec: dict, obj_key: str, obj: Any):
        log.trace("Validating AWS string '{}'".format(obj_key))

        # Validate string if object is a string
        if isinstance(obj, str):
            self.__validate_string(spec_key, spec, obj_key, obj)
            return

        # AWS strings are dicts
        if isinstance(obj, dict) and len(obj) == 1 and next(iter(obj)) in self.AWS_STRING_FUNCTIONS:
            return

        self.__log_validation_error(
            spec_key,
            spec,
            obj_key,
            obj,
            "Expecting a string or an AWS CloudFormation intrinsic function, received {}".format(type(obj).__name__),
        )

    def __is_boolean(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, bool)

    def __validate_boolean(self, spec_key: str, spec: dict, obj_key: str, obj: Any):
        log.trace("Validating boolean '{}'".format(obj_key))

        # Validate object type
        if not isinstance(obj, bool):
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting boolean, received {}".format(type(obj).__name__),
            )

    def __is_dict(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, dict)

    def __validate_dict(self, spec_key: str, spec: dict, obj_key: str, obj: Any):
        log.trace("Validating dict '{}'".format(obj_key))
        if not isinstance(obj, dict):
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting dict, received '{}'".format(type(obj).__name__),
            )
            return

        # Validate each spec key
        validated_keys = []
        for child_spec_key in sorted(spec):
            # Skip spec meta keys (starting with underscore)
            if child_spec_key.startswith(self.meta_prefix):
                continue

            fq_spec_key = spec_key + "." + child_spec_key
            validated_keys += self.__validate_dict_item(fq_spec_key, spec[child_spec_key], obj_key, obj)

        # Validate there are no extra obj keys
        unknown_keys = [k for k in sorted(obj) if k not in validated_keys]
        for unknown_key in unknown_keys:
            fq_obj_key = obj_key + "." + unknown_key
            self.__log_validation_error(spec_key, spec, fq_obj_key, obj, f"Unsupported property {unknown_key}")

    def __validate_dict_item(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> list[str]:  # noqa: C901
        # Retrieve all keys matching the spec
        if self.__spec_key("KeyEnum") in spec:
            # Keys in the enum
            keys = [k for k in obj if k in spec[self.__spec_key("KeyEnum")]]
        elif self.__spec_key("KeyRegex") in spec:
            # Keys matching the regex
            keys = [k for k in obj if re.match(r"^({})$".format(spec[self.__spec_key("KeyRegex")]), k)]
        else:
            # Key same as the spec key
            key = spec_key.split(".")[-1]
            if key in obj:
                keys = [key]
            else:
                keys = []

        # Remove all keys in KeyNotEnum
        if self.__spec_key("KeyNotEnum") in spec:
            keys = [k for k in keys if k not in spec[self.__spec_key("KeyNotEnum")]]

        fq_obj_key = obj_key + "." + spec_key.split(".")[-1]

        # Check number of matching keys is within the cardinality bounds
        cardinality_min, cardinality_max = self.__parse_dict_cardinality(spec_key, spec, obj_key, obj)
        if len(keys) < cardinality_min or len(keys) > cardinality_max:
            if len(keys) == 0 and cardinality_min == 1 and cardinality_max == 1:
                self.__log_validation_error(spec_key, spec, fq_obj_key, obj, "Missing required property")
            elif cardinality_min == 0 and cardinality_max == 0:
                self.__log_validation_error(spec_key, spec, fq_obj_key, obj, f"Unsupported property {str(keys)}")
            elif cardinality_min == cardinality_max:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    fq_obj_key,
                    obj,
                    "Found {} matching keys, expecting {}".format(len(keys), cardinality_min),
                )
            elif len(keys) < cardinality_min:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    fq_obj_key,
                    obj,
                    "Found {} matching keys, expecting at least {}".format(len(keys), cardinality_min),
                )
            elif len(keys) > cardinality_max:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    fq_obj_key,
                    obj,
                    "Found {} matching keys, expecting at most {}".format(len(keys), cardinality_max),
                )
        else:
            # Validate each key
            for key in keys:
                fq_obj_key = obj_key + "." + key
                self.__validate(spec_key, spec, fq_obj_key, obj[key])

        return keys

    def __is_eval_boolean(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, bool) or isinstance(obj, dict) and len(obj) == 1 and next(iter(obj)).startswith("Spec::")

    def __validate_eval_boolean(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> bool:
        log.trace("Validating eval-boolean '{}'".format(obj_key))

        # Validate boolean if object is a boolean
        if isinstance(obj, bool):
            return self.__validate_boolean(spec_key, spec, obj_key, obj)

        # Check if object is a Spec:: function
        if isinstance(obj, dict) and len(obj) == 1 and next(iter(obj)).startswith("Spec::"):
            return True

        self.__log_validation_error(
            spec_key,
            spec,
            obj_key,
            obj,
            "Expecting a boolean or eval, received {}".format(type(obj).__name__),
        )
        return False

    def __is_float(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, (float, int)) or (isinstance(obj, str) and spec.get(self.__spec_key("FloatTypecast"), True))

    def __validate_float(self, spec_key: str, spec: dict, obj_key: str, obj: Any):  # noqa: C901
        log.trace("Validating float '{}'".format(obj_key))

        # Validate object type
        if isinstance(obj, (float, int)):
            value = float(obj)
        elif isinstance(obj, str) and spec.get(self.__spec_key("FloatTypecast"), True):
            # Try to cast string to float
            try:
                value = float(obj)
            except ValueError:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Expecting float, received non-float {}".format(type(obj).__name__),
                )
                return
        else:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting float, received {}".format(type(obj).__name__),
            )
            return

        # Validate minimum value constraint
        if self.__spec_key("FloatMinValue") in spec:
            min_value = self.__eval(spec_key, spec[self.__spec_key("FloatMinValue")], obj_key, obj)
            if value < min_value:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Minimum value is {}, received {}".format(min_value, value),
                )

        # Validate maximum value constraint
        if self.__spec_key("FloatMaxValue") in spec:
            max_value = self.__eval(spec_key, spec[self.__spec_key("FloatMaxValue")], obj_key, obj)
            if value > max_value:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Maximum value is {}, received {}".format(max_value, value),
                )

        # Validate Enum constraint
        if self.__spec_key("FloatEnum") in spec:
            enum_values = self.__eval(spec_key, spec[self.__spec_key("FloatEnum")], obj_key, obj)
            if value not in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Value must be one of {}, received '{}'".format(enum_values, value),
                )
        if self.__spec_key("FloatNotEnum") in spec:
            enum_values = self.__eval(spec_key, spec[self.__spec_key("FloatNotEnum")], obj_key, obj)
            if value not in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Value must NOT be one of {}, received '{}'".format(enum_values, value),
                )

    def __is_freeform(self, spec: dict, obj: Any) -> bool:
        return True

    def __validate_freeform(self, spec_key: str, spec: dict, obj_key: str, obj: Any):
        log.trace("Validating freeform '{}'".format(obj_key))
        # Nothing to do
        return

    def __is_int(self, spec: dict, obj: Any) -> bool:
        if isinstance(obj, int) or isinstance(obj, str) and spec.get(self.__spec_key("IntTypecast"), True):
            return True

        return False

    def __validate_int(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> None:  # noqa: C901
        log.trace("Validating int '{}'".format(obj_key))

        # Validate object type
        if isinstance(obj, int):
            value = obj
        elif isinstance(obj, str) and spec.get(self.__spec_key("IntTypecast"), True):
            # Try to cast string to int
            try:
                value = int(obj)
            except ValueError:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Expecting int, received non-int {}".format(type(obj).__name__),
                )
                return
        else:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting int, received {}".format(type(obj).__name__),
            )
            return

        # Validate minimum value constraint
        if self.__spec_key("IntMinValue") in spec:
            min_value = self.__eval(spec_key, spec[self.__spec_key("IntMinValue")], obj_key, obj)
            if value < min_value:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Minimum value is {}, received {}".format(min_value, value),
                )

        # Validate maximum value constraint
        if self.__spec_key("IntMaxValue") in spec:
            max_value = self.__eval(spec_key, spec[self.__spec_key("IntMaxValue")], obj_key, obj)
            if value > max_value:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Maximum value is {}, received {}".format(max_value, value),
                )

        # Validate Enum constraint
        if self.__spec_key("IntEnum") in spec:
            enum_values = self.__eval(spec_key, spec[self.__spec_key("IntEnum")], obj_key, obj)
            if value not in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Value must be one of {}, received '{}'".format(enum_values, value),
                )
        if self.__spec_key("IntNotEnum") in spec:
            enum_values = self.__eval(spec_key, spec[self.__spec_key("IntNotEnum")], obj_key, obj)
            if value not in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Value must NOT be one of {}, received '{}'".format(enum_values, value),
                )

        if self.__spec_key("IntMultipleOf") in spec:
            value_multiple = self.__eval(spec_key, spec[self.__spec_key("IntMultipleOf")], obj_key, obj)
            if (value % value_multiple) != 0:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Value must be a multiple of {}, received '{}'".format(value_multiple, value),
                )

    def __is_json_string(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, str)

    def __validate_json_string(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> None:

        log.trace("Validating json-string '{}'".format(obj_key))

        # Validate object type
        if isinstance(obj, str):
            value = obj
        else:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting json-string, received {}".format(type(obj).__name__),
            )
            return

        try:
            json.loads(value)
        except Exception as e:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Value of the string is not valid JSON - {}".format(e),
            )
            return

    def __is_list(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, list) or spec.get(self.__spec_key("ListAllowSingular"), False)

    def __validate_list(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> None:
        log.trace("Validating list '{}'".format(obj_key))

        if not isinstance(obj, list) and spec.get(self.__spec_key("ListAllowSingular"), False):
            obj = [obj]

        if not isinstance(obj, list):
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting list, received '{}'".format(type(obj).__name__),
            )
            return

        # Ensure list matches specified list cardinality
        min_length, max_length = self.__parse_list_length(spec_key, spec, obj_key, obj)
        fq_obj_key = obj_key + "." + spec_key.split(".")[-1]
        if (len(obj) < min_length or len(obj) > max_length) and min_length == max_length:
            self.__log_validation_error(
                spec_key,
                spec,
                fq_obj_key,
                obj,
                "List length is {}, but must be {}".format(len(obj), min_length),
            )
        elif len(obj) < min_length:
            self.__log_validation_error(
                spec_key,
                spec,
                fq_obj_key,
                obj,
                "List length is {}, but must be at least {}".format(len(obj), min_length),
            )
        elif len(obj) > max_length:
            self.__log_validation_error(
                spec_key,
                spec,
                fq_obj_key,
                obj,
                "List length is {}, but must be at most {}".format(len(obj), max_length),
            )

        # Validate each item in the list
        for index, item in enumerate(obj):
            fq_obj_key = "{}[{}]".format(obj_key, index)
            self.__validate(spec_key, spec[self.__spec_key("ListItemSpec")], fq_obj_key, item)

    def __validate_multiple(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> None:  # noqa: C901
        specs = spec[self.__spec_key("MultipleSpecs")]
        spec_matched = False
        for new_spec in specs:
            new_spec_type = new_spec.get(self.__spec_key("Type"), "dict")
            if new_spec_type == "aws-string" and self.__is_aws_string(new_spec, obj):
                spec_matched = True
                self.__validate_aws_string(spec_key, new_spec, obj_key, obj)
            if new_spec_type == "boolean" and self.__is_boolean(new_spec, obj):
                spec_matched = True
                self.__validate_boolean(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "dict" and self.__is_dict(new_spec, obj):
                spec_matched = True
                self.__validate_dict(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "float" and self.__is_float(new_spec, obj):
                spec_matched = True
                self.__validate_float(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "freeform" and self.__is_freeform(new_spec, obj):
                spec_matched = True
                self.__validate_freeform(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "int" and self.__is_int(new_spec, obj):
                spec_matched = True
                self.__validate_int(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "json-string" and self.__is_json_string(new_spec, obj):
                spec_matched = True
                self.__validate_json_string(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "list" and self.__is_list(new_spec, obj):
                spec_matched = True
                self.__validate_list(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "scalar" and self.__is_scalar(new_spec, obj):
                spec_matched = True
                self.__validate_scalar(spec_key, new_spec, obj_key, obj)
            elif new_spec_type == "string" and self.__is_string(new_spec, obj):
                spec_matched = True
                self.__validate_string(spec_key, new_spec, obj_key, obj)

            if spec_matched:
                if self.__spec_key("Warning") in new_spec:
                    self.__log_validation_warning(
                        spec_key,
                        new_spec,
                        obj_key,
                        obj,
                        new_spec[self.__spec_key("Warning")],
                    )

                break

        if not spec_matched:
            spec_types = ", ".join(list({s.get(self.__spec_key("Type"), "dict") for s in specs}))
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting one of [{}], received {}".format(spec_types, type(obj).__name__),
            )

    def __is_scalar(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, (str, int, bool))

    def __validate_scalar(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> None:
        if isinstance(obj, str):
            return self.__validate_string(spec_key, spec, obj_key, obj)
        elif isinstance(obj, int):
            return self.__validate_int(spec_key, spec, obj_key, obj)
        elif isinstance(obj, bool):
            return self.__validate_boolean(spec_key, spec, obj_key, obj)
        else:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting a scalar type [bool, int, str], received {}".format(type(obj).__name__),
            )

    def __is_string(self, spec: dict, obj: Any) -> bool:
        return isinstance(obj, str) or spec.get(self.__spec_key("StringTypecast"), False)

    def __validate_string(self, spec_key: str, spec: dict, obj_key: str, obj: Any) -> None:  # noqa: C901
        log.trace("Validating string '{}'".format(obj_key))

        # Validate object type
        if isinstance(obj, str):
            value = obj
        elif spec.get(self.__spec_key("StringTypecast"), False):
            # Try to cast to string
            try:
                value = str(obj)
            except ValueError:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    obj,
                    "Expecting str, received non-str {}".format(type(obj).__name__),
                )
                return
        else:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                obj,
                "Expecting str, received {}".format(type(obj).__name__),
            )
            return

        if self.__spec_key("StringEnum") in spec:
            # Validate Enum constraint
            enum_values = self.__eval(spec_key, spec[self.__spec_key("StringEnum")], obj_key, value)
            if value not in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    value,
                    "Value must be one of {}, received '{}'".format(enum_values, value),
                )
        if self.__spec_key("StringNotEnum") in spec:
            # Validate NotEnum constraint
            enum_values = self.__eval(spec_key, spec[self.__spec_key("StringNotEnum")], obj_key, value)
            if value in enum_values:
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    value,
                    "Value must NOT be one of {}, received '{}'".format(enum_values, value),
                )
        if self.__spec_key("StringRegex") in spec:
            # Validate Regex constraint
            value_regex = self.__eval(spec_key, spec[self.__spec_key("StringRegex")], obj_key, value)
            if not re.match("^({})$".format(value_regex), value):
                self.__log_validation_error(
                    spec_key,
                    spec,
                    obj_key,
                    value,
                    "String must match regex '{}', received '{}'".format(value_regex, value),
                )

        # Ensure string is the correct length
        min_length, max_length = self.__parse_string_length(spec_key, spec, obj_key, value)
        if (len(value) < min_length or len(value) > max_length) and min_length == max_length:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                value,
                "String must be {} characters long, received '{}' ({}) characters".format(min_length, value, len(value)),
            )
        elif len(value) < min_length:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                value,
                "String must be at least {} characters long, received '{}' ({}) characters".format(min_length, value, len(value)),
            )
        elif len(value) > max_length:
            self.__log_validation_error(
                spec_key,
                spec,
                obj_key,
                value,
                "String must be at most {} characters long, received '{}' ({}) characters".format(max_length, value, len(value)),
            )

    def __eval_if(self, spec_key: str, statement_value: Any, obj_key: str, obj: Any) -> Any:
        # Contents must be a list
        if not isinstance(statement_value, list):
            raise Exception("Expected a list for If statement '{}', received '{}'".format(spec_key, type(statement_value).__name__))
        # Contents list must contain 3 items
        if len(statement_value) < 1 or len(statement_value) > 3:
            raise Exception(
                "Expected between 1 and 3 items (statement, true value, false value) for If statement '{}'".format(spec_key)
            )

        # Default true and false values to True and False, if not provided
        true_value = statement_value[1] if len(statement_value) > 1 else True
        false_value = statement_value[2] if len(statement_value) > 2 else False

        log.trace("Evaluating Spec::If: {}".format(statement_value))
        if self.__eval(spec_key, statement_value[0], obj_key, obj):
            return self.__eval(spec_key, true_value, obj_key, obj)
        else:
            return self.__eval(spec_key, false_value, obj_key, obj)

    def __eval_or(self, spec_key: str, statement_value: Any, obj_key: str, obj: Any) -> bool:
        # Contents must be a list
        if not isinstance(statement_value, list):
            raise Exception("Expected a list for Or statement '{}', received '{}'".format(spec_key, type(statement_value).__name__))
        # Contents list must contain 1 or more items
        if len(statement_value) < 1:
            raise Exception("Expected a list with one or more items for Or statement '{}'".format(spec_key))

        log.trace("Evaluating Spec::Or: {}".format(statement_value))
        # Return true if any items are true
        for or_statement in statement_value:
            if self.__eval(spec_key, or_statement, obj_key, obj):
                return True

        # Everything validates
        return False

    def __eval_and(self, spec_key: str, statement_value: Any, obj_key: str, obj: Any) -> bool:
        # Contents must be a list
        if not isinstance(statement_value, list):
            raise Exception(
                "Expected a list for And statement '{}', received '{}'".format(spec_key, type(statement_value).__name__)
            )
        # Contents list must contain 1 or more items
        if len(statement_value) < 1:
            raise Exception("Expected a list with 1 or more items for And statement '{}'".format(spec_key))

        log.trace("Evaluating Spec::And: {}".format(statement_value))
        # Return false if any items are false
        for statement in statement_value:
            if self.__eval(spec_key, statement, obj_key, obj):
                return False

        # Everything validates
        return True

    def __eval_not(self, spec_key: str, statement_value: Any, obj_key: str, obj: Any) -> bool:
        log.trace("Evaluating Spec::Not: {}".format(statement_value))
        return not self.__eval(spec_key, statement_value, obj_key, obj)

    def __eval_property(self, spec_key: str, statement_value: Any, obj_key: str, obj: Any) -> bool:
        log.trace("Evaluating Spec::Property: {}, {}".format(statement_value, spec_key))
        if not isinstance(statement_value, list):
            raise Exception(
                "Expected a list for Property statement '{}', received '{}'".format(spec_key, type(statement_value).__name__)
            )
        if len(statement_value) < 1 or len(statement_value) > 2:
            raise Exception(
                "Expected a list with 1 or 2 items (property name, property value) for Property statement '{}'".format(spec_key)
            )

        property_name = statement_value[0]

        if len(statement_value) == 2:
            # Compare expected value and actual value
            expected_value = statement_value[1]
            property_value = obj.get(property_name, None)
            if expected_value == property_value:
                return True
        else:
            if property_name in obj:
                return True

        # Property check failed
        return False

    def __eval_switch(self, spec_key: str, statement_value: Any, obj_key: str, obj: Any) -> Any:
        log.trace("Evaluating Spec::Switch: {}".format(statement_value))
        if not isinstance(statement_value, list):
            raise Exception(
                "Expected a list for Switch statement '{}', received '{}'".format(spec_key, type(statement_value).__name__)
            )

        for item in statement_value:
            if not isinstance(item, list):
                # No condition, just return the value
                return self.__eval(spec_key, item, obj_key, obj)

            if len(item) != 2:
                raise Exception("Expected a list with 2 items (condition, value) for Switch item '{}'".format(spec_key))

            if self.__eval(spec_key, item[0], obj_key, obj):
                return self.__eval(spec_key, item[1], obj_key, obj)

        raise Exception("No matching Switch condition for '{}'".format(spec_key))

    def __eval(self, spec_key: str, statement: Any, obj_key: str, obj: Any) -> Any:
        # Return the value if doesn't look like a statement
        if not isinstance(statement, dict) or len(statement) != 1:
            return statement

        statement_key = next(iter(statement))
        statement_value = statement[statement_key]

        if statement_key == "Spec::If":
            return self.__eval_if(spec_key, statement_value, obj_key, obj)
        elif statement_key == "Spec::Or":
            return self.__eval_or(spec_key, statement_value, obj_key, obj)
        elif statement_key == "Spec::And":
            return self.__eval_and(spec_key, statement_value, obj_key, obj)
        elif statement_key == "Spec::Not":
            return self.__eval_not(spec_key, statement_value, obj_key, obj)
        elif statement_key == "Spec::Property":
            return self.__eval_property(spec_key, statement_value, obj_key, obj)
        elif statement_key == "Spec::Switch":
            return self.__eval_switch(spec_key, statement_value, obj_key, obj)
        else:
            # Not a statement - just return it
            return statement
