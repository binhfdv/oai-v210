def generate_cuup_config(
    f1_ip,
    cu_cp_ip,
    cu_up_ip,
    n3_ip,
    near_ric_ip,
    template_path='cuup.conf',
    output_path='cuup_generated.conf'
):
    # Read the CUUP template
    with open(template_path, 'r') as f:
        config = f.read()

    # Replace placeholders with actual values
    replacements = {
        '@F1_IP_ADDRESS@': f1_ip,
        '@CU_CP_IP_ADDRESS@': cu_cp_ip,
        '@CU_UP_IP_ADDRESS@': cu_up_ip,
        '@N3_IP_ADDRESS@': n3_ip,
        '@NEAR_RIC_IP_ADDRESS@': near_ric_ip
    }

    for key, value in replacements.items():
        config = config.replace(key, value)

    # Write the result to the output file
    with open(output_path, 'w') as f:
        f.write(config)

    print(f"Generated CUUP config at: {output_path}")


if __name__ == '__main__':
    # Define your actual IPs here
    F1_IP = '192.168.70.140'
    CU_CP_IP = '192.168.70.139'
    CU_UP_IP = '192.168.70.140'
    N3_IP = '192.168.70.140'
    NEAR_RIC_IP = '192.168.70.154'

    generate_cuup_config(
        f1_ip=F1_IP,
        cu_cp_ip=CU_CP_IP,
        cu_up_ip=CU_UP_IP,
        n3_ip=N3_IP,
        near_ric_ip=NEAR_RIC_IP
    )
