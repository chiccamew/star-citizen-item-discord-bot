## copy and paste these lines one by one
### Create project
    /project_create name:WikeloIdris

## Set Project Requirement
    /project_add_item project_name:WikeloIdris item_name:Wikelo Favor amount:50
#
    /project_add_item project_name:WikeloIdris item_name:Polaris Bit amount:50
#
    /project_add_item project_name:WikeloIdris item_name:DCHS-05 Orbital Positioning Comp-Board amount:50
#
    /project_add_item project_name:WikeloIdris item_name:Carinite amount:50
#
    /project_add_item project_name:WikeloIdris item_name:Irradiated Valakkar Fang (Apex) amount:50
#
    /project_add_item project_name:WikeloIdris item_name:MG Script amount:50
#
    /project_add_item project_name:WikeloIdris item_name:Ace Interceptor Helmet amount:50
#
    /project_add_item project_name:WikeloIdris item_name:Irradiated Valakkar Pearl (Grade AAA) amount:30
#
    /project_add_item project_name:WikeloIdris item_name:UEE 6th Platoon Medal (Pristine) amount:30
#
    /project_add_item project_name:WikeloIdris item_name:Carinite (Pure) amount:30
#
    /project_add_item project_name:WikeloIdris item_name:ASD Secure Drive amount:30
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-PWL-1 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-PWL-2 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-PWL-3 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-RGL-1 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-RGL-2 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-RGL-3 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-XTL-1 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-XTL-2 amount:5
#
    /project_add_item project_name:WikeloIdris item_name:RCMBNT-XTL-3 amount:5

## Set Recipe
    /recipe_add output_item:Wikelo Favor input_item:MG Script ratio:50
#
    /recipe_add output_item:Polaris Bit input_item:Quantanium ratio:24

## Check Project Status
    /status project_name:WikeloIdris

# Deposit Some Items
    /deposit item_name:Wikelo Favor amount:30
#
    /deposit item_name:MG Script amount:120
#
    /deposit item_name:Polaris Bit amount:10
#
    /deposit item_name:Quantanium amount:60

## Check Project Status after depositing some items
    /status project_name:WikeloIdris

## Check who has what item
    /locate item_name:Wikelo Favor

## Test Withdraw Item
    /withdraw_item item_name:Polaris Bit amount:3
#
    /modify_item_qty item_name:Wikelo Favor quantity:5

## Check own stock
    /my_stock

## Simulate Item production
    /production item_name:Wikelo Favor

## Pin a project status message
    /dashboard_set project_name:WikeloIdris

## Add More item deposit, the pinned message should be updated
    /deposit item_name:Wikelo Favor amount:40
