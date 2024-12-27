import core_framework as util
from glob import glob
import yaml
import os
import core_logging as log


class SpecLibrary:

    module_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    SPEC_FILE_GLOBS = [
        os.path.join(module_dir, "compiler", "consumables", "**", "specs", "*.yaml")
    ]

    specs: dict
    compiled_specs: list[dict]
    meta_prefix: str

    def __init__(
        self, spec_file_globs: list[str] = SPEC_FILE_GLOBS, meta_prefix: str = "_"
    ):
        self.specs = {}
        self.compiled_specs = []
        self.meta_prefix = meta_prefix

        # Load all specs
        for spec_file_glob in spec_file_globs:
            self.__load(spec_file_glob)

    def get_spec(self, spec_name):
        if spec_name not in self.specs:
            return None

        if spec_name not in self.compiled_specs:
            self.specs[spec_name] = self.__compile(spec_name, self.specs[spec_name])
            self.compiled_specs.append(spec_name)

        return self.specs[spec_name]

    def get_specs(self) -> dict:
        specs = {}
        for spec_name in self.specs:
            specs[spec_name] = self.get_spec(spec_name)

        return specs

    def __spec_key(self, key: str) -> str:
        return self.meta_prefix + key

    def __is_primitive_type(self, item_type):
        """
        Returns true if the provided type is a primitive type, false otherwise
        * Custom types have upper case characters (eg. Component) or colons (eg. Common::MetaData)
        * Primitive types are all lower-case and don't contain colons, eg. int, string, boolean, json-string
        """
        return item_type.islower() and ":" not in item_type

    def __load(self, file_glob: str):
        # Load consumable specs
        file_names = glob(file_glob, recursive=True)
        for file_name in file_names:
            with open(file_name) as f:
                spec = yaml.safe_load(f)
                if not spec:
                    continue
                util.deep_merge_in_place(self.specs, spec)

    def __compile(self, spec_key: str, spec: dict, layer=0) -> dict:  # noqa: C901
        spec = util.deep_copy(spec)

        if layer > 15:
            log.warn(
                "Validation spec too deep, stopping compilation '{}'".format(spec_key)
            )
            spec[self.__spec_key("Type")] = "freeform"

        # Default the spec type to 'dict' if not specified
        spec_type = spec.get(self.__spec_key("Type"), "dict")
        spec[self.__spec_key("Type")] = spec_type

        log.trace("Compiling spec '{}' with type '{}'".format(spec_key, spec_type))

        if spec_type == "list":
            fq_spec_key = spec_key + "[]"

            if (
                self.__spec_key("ListItemType") not in spec
                and self.__spec_key("ListItemSpec") not in spec
            ):
                raise Exception(
                    "List type must define _ListItemType or _ListItemSpec, spec key '{}'".format(
                        spec_key
                    )
                )

            # Convert ListItemType into ListItemSpec
            if self.__spec_key("ListItemType") in spec:
                item_type = spec.pop(self.__spec_key("ListItemType"))
                item_spec = spec.get(self.__spec_key("ListItemSpec"), {})

                if self.__is_primitive_type(item_type):
                    # Map primitive type straight through to ListItemSpec
                    spec[self.__spec_key("ListItemSpec")] = util.deep_merge(
                        {self.__spec_key("Type"): item_type}, item_spec
                    )
                elif item_type in self.specs:
                    # Load custom type into ListItemSpec
                    custom_type_spec = self.specs[item_type]

                    # Default the spec type to 'dict', to avoid circular loops
                    custom_type_spec[self.__spec_key("Type")] = custom_type_spec.get(
                        self.__spec_key("Type"), "dict"
                    )

                    # Merge loaded item spec into existing spec
                    spec[self.__spec_key("ListItemSpec")] = util.deep_merge(
                        custom_type_spec, item_spec
                    )
                else:
                    raise Exception(
                        "ERROR: Spec type '{}' does not exist".format(item_type)
                    )

            # Compile the ListItemSpec
            spec[self.__spec_key("ListItemSpec")] = self.__compile(
                fq_spec_key, spec[self.__spec_key("ListItemSpec")], layer + 1
            )

        elif spec_type == "dict":
            # Compile the spec's child keys
            for child_spec_key in sorted(spec):
                # Skip meta keys
                if child_spec_key.startswith(self.meta_prefix):
                    continue

                fq_child_spec_key = spec_key + "." + child_spec_key
                compiled = self.__compile(
                    fq_child_spec_key, spec[child_spec_key], layer + 1
                )
                util.deep_merge_in_place(
                    spec[child_spec_key],
                    compiled,
                    should_merge=lambda k: k == self.__spec_key("Type")
                    or not k.startswith(self.meta_prefix),
                )
        elif self.__is_primitive_type(spec_type):
            # Nothing to compile for primitive types
            pass
        else:
            # Custom type
            if spec_type not in self.specs:
                raise Exception(
                    "ERROR: Spec type '{}' does not exist".format(spec_type)
                )

            # Load custom type
            custom_type_spec = self.specs[spec_type]

            # Default the spec type to 'dict', to avoid circular loops
            custom_type_spec[self.__spec_key("Type")] = custom_type_spec.get(
                self.__spec_key("Type"), "dict"
            )

            # Merge type into spec
            util.deep_merge_in_place(
                spec,
                custom_type_spec,
                should_merge=lambda k: k == self.__spec_key("Type")
                or not k.startswith(self.meta_prefix),
            )

            # Re-compile spec since type would have changed from the merge
            spec = self.__compile(spec_key, spec, layer + 1)

        return spec
