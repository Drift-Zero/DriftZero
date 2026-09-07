export type Density='comfortable'|'compact'
export type TimestampFormat='relative'|'absolute'
export type TimeZoneMode='local'|'utc'
export type ConnectionMode='demo'|'live'
export type OperatorRole='viewer'|'operator'|'admin'
export type NotifySeverity='info'|'low'|'medium'|'high'|'critical'

export interface WorkspaceSettings{name:string;environmentLabel:string;actor:string;role:OperatorRole}
export interface AppearanceSettings{density:Density;reducedMotion:boolean;timestampFormat:TimestampFormat;timeZone:TimeZoneMode;scoreDecimals:number;showDemoControls:boolean}
export interface ConnectionSettings{mode:ConnectionMode;baseUrl:string;autoRefreshSeconds:number}
export interface NotificationSettings{desktop:boolean;minimumSeverity:NotifySeverity;incidents:boolean;recovery:boolean}
export interface AppSettings{workspace:WorkspaceSettings;appearance:AppearanceSettings;connection:ConnectionSettings;notifications:NotificationSettings}

export const DENSITIES:Density[]=['comfortable','compact']
export const TIMESTAMP_FORMATS:TimestampFormat[]=['relative','absolute']
export const TIME_ZONES:TimeZoneMode[]=['local','utc']
export const CONNECTION_MODES:ConnectionMode[]=['demo','live']
export const OPERATOR_ROLES:OperatorRole[]=['viewer','operator','admin']
/* Ordered weakest first so a minimum-severity preference can be compared by index. */
export const NOTIFY_SEVERITIES:NotifySeverity[]=['info','low','medium','high','critical']
export const AUTO_REFRESH_CHOICES=[0,15,30,60,300]
