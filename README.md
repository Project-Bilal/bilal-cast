# Gameplan Overview
Quick summary of how to approach a working solution using both a device based scheduler and app based onboarding and configurations.

#### Use Bilal Companion app to onboard device to wifi via bluetooth
1. Find BilalCast Device using bluetooth
2. Search for available networks
3. Select desired network
4. Submit network ssid and pw to BilalCast Device
5. Wait for device to come online and very its status.  This can be done by mDNS discovery, or device communicating its status via bluetooth. 
6. Set BilalCast RTC to UTC using worldtimezone's api (https://worldtimeapi.org/api/timezone/utc.txt)


#### Configure BilalCast Device using Companion App
1. Save BilalCast device's identification on users profile.  
2. Allow cofiguration options for BilalCast (Location, Calculation methods, athans, volumes, reminders)
3. Send configuration information to BilalCast device. (via http or bt)

#### Trigger Athans
1. When configurations present start athan scheduler
2. When configurations updated, restart athan scheduler
3. Reset after every call
4. Fetch next prayer using aladhan api.
5. UTC timezone


#### General BilalCast Features
1. online status
2. wifi disconnect/reset via http/bt
3. wifi strength
4. test casting to speaker from device



