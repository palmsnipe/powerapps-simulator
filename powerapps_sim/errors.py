"""Power Fx numeric ErrorKind values, separate from simulator diagnostic kinds.

Values follow Microsoft.PowerFx.ErrorKind at the pinned reference revision:
https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Public/ErrorKind.cs
Microsoft's MIT notice is retained in conformance_cases/MICROSOFT-LICENSE.txt.
"""
ERROR_KINDS = {
    'None': 0, 'Sync': 1, 'MissingRequired': 2, 'CreatePermission': 3,
    'EditPermissions': 4, 'DeletePermissions': 5, 'Conflict': 6, 'NotFound': 7,
    'ConstraintViolated': 8, 'GeneratedValue': 9, 'ReadOnlyValue': 10,
    'Validation': 11, 'Unknown': 12, 'Div0': 13, 'BadLanguageCode': 14,
    'BadRegex': 15, 'InvalidFunctionUsage': 16, 'FileNotFound': 17,
    'AnalysisError': 18, 'ReadPermission': 19, 'NotSupported': 20,
    'InsufficientMemory': 21, 'QuotaExceeded': 22, 'Network': 23, 'Numeric': 24,
    'InvalidArgument': 25, 'Internal': 26, 'NotApplicable': 27, 'Timeout': 28,
    'ServiceUnavailable': 29, 'InvalidJSON': 30, 'Custom': 1000,
    # Canvas documentation also exposes these singular names.
    'EditPermission': 4, 'DeletePermission': 5, 'ConstraintViolation': 8,
}


def error_number(kind):
    if type(kind) is int:
        return kind
    alias = {'Name': 'AnalysisError', 'Cycle': 'AnalysisError', 'Unsupported': 'NotSupported', 'Type': 'InvalidArgument'}
    return ERROR_KINDS.get(alias.get(kind, kind), ERROR_KINDS['Unknown'])


def error_name(kind):
    if type(kind) is int:
        return next((name for name, value in ERROR_KINDS.items() if kind == value), kind)
    return kind
