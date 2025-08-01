dearpygui, pymavlink, python are requirements. 

Change your Laptop IP in ethernet settings to manual IPv4 192.168.144.100 (the default one that pops up in the GUI). 

COM Port and Baud rate does not matter (leave it at default). STM 32 and Pixhawk need to be powered on. Connect STM32 and laptop via an ethernet switch. 

Data should come as soon as it shows UDP connected, Serial Connected. If it does not, restart the cube orange. 

The EDF beeps on powering on. Select M1. The beeping should stop.

Then select record and add an appropriate file name to save data. This triggers a set pattern of pulses (can be changed in the GUI code _run_throttle_pattern in the ui\main_window.py) for timing the stm data to daq data. 

Then select a throttle and time in ms. 

Then click single command. 

If you want to stop it in the middle click STOP. (ARM, DISARM are useless buttons) 

For continuous command you can slide the slider and give different throttles. Ensure that you press STOP before starting a continuous command because otherwise it will start at the previously requested PWM (can be changed) 

It logs: 

UNIX time
stm32_timestamp:  float  # STM32 Timestamp
pixhawk_timestamp: float  # Pixhawk Timestamp  
thrust1:         float   # Thrust 1
thrust2:         float   # Thrust 2
thrust3:         float   # Thrust 3
thrust4:         float   # Thrust 4
thrust5:         float   # Thrust 5
thrust6:         float   # Thrust 6
voltage:         float   # Voltage
current:         float   # Current
rpm:             float   # RPM
temperature:     float   # Temperature
torque:          float   # Torque
load:            float   # Load
baro_t:          float
baro_p:          float
throttle percentage. 
